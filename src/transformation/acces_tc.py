"""Accès en transport en commun : pour chaque site (culture, tourisme, événement), dit si on peut aller de sa gare la plus proche au site en transport en commun.
Remplit lieu.acces_tc, utilisé par l'onglet Analyse (lib/analyse.py) pour classer les sites : à pied, en transport en commun ou en voiture seule.

Usage : python src/transformation/acces_tc.py   (les gares, les sites, les trains et les bus doivent déjà être chargés : voir transformation.py)
Relançable sans risque : acces_tc est recalculé pour tous les sites. Environ 5 minutes, surtout pour lire les passages.

Règle de gestion : un site est accessible en transport en commun si, depuis un arrêt à RAYON_ARRET_KM ou moins de sa gare la plus proche, on atteint
un arrêt à RAYON_ARRET_KM ou moins du site avec au plus CORRESPONDANCES_MAX correspondances. Une correspondance : changer de ligne à un même arrêt
ou entre deux arrêts à RAYON_CORRESPONDANCE_KM ou moins l'un de l'autre. Les horaires ne sont pas vérifiés (seulement l'existence du chemin).
Seuls les sites à plus de SEUIL_PIED_KM de leur gare sont calculés : les autres sont à pied (acces_tc faux).
Lignes comptées : bus, tram, métro, bateau, téléphérique des réseaux urbains, cars TER et TER. Les trains grandes lignes (TGV, Intercités…) ne
servent pas au dernier kilomètre. Limite des données : seuls les 21 réseaux urbains, l'Île-de-France et les cars TER sont en base, pas les cars
régionaux ou départementaux (ZOU!, liO, BreizhGo…) : hors de ces villes, un site desservi par un car régional est compté « voiture seule ».
Distances à vol d'oiseau sur une projection plane (lib/reseau_ferre.py), suffisante pour la France continentale.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pandas as pd
import sqlalchemy as sa
from scipy.spatial import cKDTree

from lib.analyse import SEUIL_PIED_KM
from lib.db.connection import get_engine
from lib.reseau_ferre import KM_PAR_DEGRE_LON, en_km  # noqa: F401 (KM_PAR_DEGRE_LON réexporté pour les tests)

RAYON_ARRET_KM = 1.5                 # marche jusqu'à l'arrêt au départ de la gare, et de l'arrêt jusqu'au site
RAYON_CORRESPONDANCE_KM = 0.3        # marche entre deux arrêts pour changer de ligne
CORRESPONDANCES_MAX = 1
TYPES_SITES = ("culture", "tourisme", "evenement")
TYPES_GRANDES_LIGNES = ("TGV INOUI", "OUIGO", "INTERCITES", "INTERCITES de nuit", "ICE", "Lyria", "Eurostar", "AVE", "Trenitalia")
CHUNK_SIZE = 5_000


def lignes_autour(arbre, lignes_par_arret, lonlat, rayon_km=RAYON_ARRET_KM):
    """Pour chaque position, l'ensemble des lignes qui s'arrêtent à rayon_km ou moins."""
    if not len(lonlat):
        return []
    return [set().union(*(lignes_par_arret[i] for i in voisins)) for voisins in arbre.query_ball_point(en_km(lonlat), rayon_km)]


def correspondances(arbre, positions):
    """{ligne : lignes qu'on peut prendre en changeant à l'un de ses arrêts (même arrêt ou arrêt à RAYON_CORRESPONDANCE_KM ou moins)}."""
    lignes_par_arret = positions["ligne_id"].tolist()
    pole = lignes_autour(arbre, lignes_par_arret, positions[["lon", "lat"]].to_numpy(), RAYON_CORRESPONDANCE_KM)
    voisines = {}
    for lignes, autour in zip(lignes_par_arret, pole):
        for ligne in lignes:
            voisines.setdefault(ligne, set()).update(autour)
    return voisines


def acces(sites, arrets, correspondances_max=CORRESPONDANCES_MAX):
    """Série booléenne indexée comme `sites` : vrai si on va de la gare au site en transport en commun avec au plus correspondances_max correspondances.
    `sites` : lon, lat, gare_lon, gare_lat (gare la plus proche, vide si aucune) ; `arrets` : lon, lat, ligne_id (une ligne par arrêt et par ligne)."""
    resultat = pd.Series(False, index=sites.index)
    avec_gare = sites.dropna(subset=["lon", "lat", "gare_lon", "gare_lat"])
    if arrets.empty or avec_gare.empty:
        return resultat
    positions = arrets.groupby(["lon", "lat"])["ligne_id"].agg(frozenset).reset_index()
    arbre = cKDTree(en_km(positions[["lon", "lat"]].to_numpy()))
    lignes_par_arret = positions["ligne_id"].tolist()
    gares = avec_gare[["gare_lon", "gare_lat"]].drop_duplicates()
    atteintes = lignes_autour(arbre, lignes_par_arret, gares.to_numpy())          # lignes prises à la gare, puis après chaque correspondance
    if correspondances_max:
        voisines = correspondances(arbre, positions)
        for _ in range(correspondances_max):
            atteintes = [lignes.union(*(voisines.get(l, ()) for l in lignes)) for lignes in atteintes]
    depuis_gare = dict(zip(map(tuple, gares.to_numpy()), atteintes))
    autour_site = lignes_autour(arbre, lignes_par_arret, avec_gare[["lon", "lat"]].to_numpy())
    resultat[avec_gare.index] = [not s.isdisjoint(depuis_gare[g]) for s, g in zip(autour_site, zip(avec_gare["gare_lon"], avec_gare["gare_lat"]))]
    return resultat


def lire(engine):
    """(sites à plus de SEUIL_PIED_KM de leur gare, avec la position de cette gare ; arrêts desservis avec leurs lignes hors grandes lignes)."""
    sites = pd.read_sql(sa.text(
        "SELECT s.id, s.lon, s.lat, g.lon AS gare_lon, g.lat AS gare_lat FROM lieu s JOIN lieu g ON g.id = s.gare_proche_id "
        "WHERE s.type IN :types AND s.distance_gare_km > :seuil").bindparams(sa.bindparam("types", expanding=True)), engine,
        params={"types": list(TYPES_SITES), "seuil": SEUIL_PIED_KM}).set_index("id")
    arrets = pd.read_sql(sa.text(
        "SELECT DISTINCT c.ligne_id, lieu.lon, lieu.lat FROM ligne l JOIN circulation c ON c.ligne_id = l.id "
        "JOIN passage p ON p.circulation_id = c.id JOIN arret a ON a.id = p.arret_id JOIN lieu ON lieu.id = a.lieu_id "
        "WHERE (l.type_transport IS NULL OR l.type_transport NOT IN :types) AND lieu.lon IS NOT NULL AND lieu.lat IS NOT NULL").bindparams(
        sa.bindparam("types", expanding=True)), engine, params={"types": list(TYPES_GRANDES_LIGNES)})
    return sites, arrets


def charger(resultat, engine=None):
    """Écrit acces_tc pour tous les sites en une transaction (faux pour ceux qui ne sont pas dans `resultat`).
    Retourne le nombre de sites accessibles en transport en commun."""
    engine = engine or get_engine()
    oui = [int(i) for i in resultat[resultat].index]
    with engine.begin() as conn:
        conn.execute(sa.text("UPDATE lieu SET acces_tc = :non WHERE type IN :types").bindparams(sa.bindparam("types", expanding=True)),
                     {"non": False, "types": list(TYPES_SITES)})
        for i in range(0, len(oui), CHUNK_SIZE):
            conn.execute(sa.text("UPDATE lieu SET acces_tc = :oui WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True)),
                         {"oui": True, "ids": oui[i:i + CHUNK_SIZE]})
    return len(oui)


def transformer():
    engine = get_engine()
    sites, arrets = lire(engine)
    if arrets.empty:
        sys.exit("Aucune ligne en base : lancer d'abord les étapes des trains et des bus (voir transformation.py)")
    nb = charger(acces(sites, arrets), engine)
    print(f"Accès en transport en commun : {nb} sites sur {len(sites)} à plus de {SEUIL_PIED_KM} km de leur gare "
          f"(au plus {CORRESPONDANCES_MAX} correspondance(s), {RAYON_ARRET_KM} km de marche à chaque bout)")
    return nb


if __name__ == "__main__":
    transformer()
