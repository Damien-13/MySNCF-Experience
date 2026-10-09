"""Logique de l'onglet « Itinéraire voyageur » du dashboard : du lieu de départ (une gare) à la destination (un lieu de culture, de tourisme
ou un événement), sans dépendance à Dash.

Usage :
    from lib.itineraire import options_gares, chercher_destinations, rechercher
    options_gares()                                          # [{"label": nom, "value": id du lieu}, …]
    chercher_destinations("chambord", "culture")             # même format, 50 résultats au plus
    r = rechercher(depart_id, destination_id, quand="2026-10-12 08:00", retour="2026-10-14 18:00")

rechercher() retourne un dict (None si un lieu est inconnu) : depart, destination, gare_arrivee, distance_km (destination → gare la plus proche),
alentours (stations vélo et arrêts de bus près de la gare d'arrivée), dernier_km (mode, détail), faisable, trajets (Navitia, jusqu'à 3),
retour (le premier trajet retour), erreur_api (texte, sinon None), trace (une polyligne [[lat, lon], …] par train du premier trajet),
sur_voie (le tracé suit les voies), pois (lieux autour de la destination, selon la catégorie).
Rien n'est stocké : l'API Navitia est appelée à chaque recherche (voir lib/navitia.py).
"""
import math
from datetime import datetime, time

import pandas as pd
import sqlalchemy as sa

from lib import navitia
from lib.db.connection import get_engine
from lib.reseau_ferre import chemin

SEUIL_PIED_KM = 1.5
SEUIL_VELO_BUS_KM = 5.0
VITESSE_MARCHE_M_MIN = 80
RAYON_ALENTOURS_KM = 0.5
RAYON_POI_KM = 5.0
MAX_POI = 150
MAX_TRAJETS = 3
KM_PAR_DEGRE_LAT = 110.57
HEURE_DEFAUT = time(8, 0)
TYPES_POI = {"tous": ("tourisme", "culture", "evenement"), "culture": ("culture", "tourisme"), "evenement": ("evenement",)}


def _types(categorie):
    return TYPES_POI.get(categorie, TYPES_POI["tous"])


def options_gares(engine=None):
    """Gares pour le menu de départ : label = nom, value = id du lieu."""
    df = pd.read_sql(sa.text("SELECT id, nom FROM lieu WHERE type = 'gare' AND nom IS NOT NULL ORDER BY nom"), engine or get_engine())
    return [{"label": nom, "value": int(i)} for i, nom in zip(df["id"], df["nom"])]


def chercher_destinations(texte, categorie="tous", engine=None, inclure=None, limite=50):
    """Lieux de la catégorie dont le nom contient `texte` (au plus `limite`, commune en plus pour distinguer les homonymes).
    `inclure` : id d'un lieu à garder dans la liste (celui déjà choisi), sinon le menu le perd."""
    types = _types(categorie)
    where, ordre, params = "type IN :types AND nom IS NOT NULL", "nom", {"types": list(types), "limite": limite}
    if texte and texte.strip():
        where += " AND nom LIKE :texte"
        ordre = "nom NOT LIKE :debut, nom"                       # les noms qui commencent par la saisie d'abord
        params.update(texte=f"%{texte.strip()}%", debut=f"{texte.strip()}%")
    requete = sa.text(f"SELECT id, nom, commune FROM lieu WHERE {where} ORDER BY {ordre} LIMIT :limite").bindparams(sa.bindparam("types", expanding=True))
    df = pd.read_sql(requete, engine or get_engine(), params=params)
    if inclure is not None and int(inclure) not in set(df["id"]):
        df = pd.concat([pd.read_sql(sa.text("SELECT id, nom, commune FROM lieu WHERE id = :id"), engine or get_engine(), params={"id": int(inclure)}), df])
    return [{"label": f"{nom} ({commune})" if commune else nom, "value": int(i)} for i, nom, commune in zip(df["id"], df["nom"], df["commune"])]


def _lieu(engine, lieu_id):
    df = pd.read_sql(sa.text(
        "SELECT lieu.id, lieu.type, lieu.nom, lieu.commune, lieu.lat, lieu.lon, lieu.gare_proche_id, lieu.distance_gare_km, gare.code_uic "
        "FROM lieu LEFT JOIN gare ON gare.lieu_id = lieu.id WHERE lieu.id = :id"), engine, params={"id": int(lieu_id)})
    if df.empty:
        return None
    ligne = df.iloc[0].astype(object).where(df.iloc[0].notna(), None).to_dict()
    ligne["id"] = int(ligne["id"])
    return ligne


def alentours(engine, lat, lon, rayon_km=RAYON_ALENTOURS_KM):
    """Nombre de stations vélo et d'arrêts de bus à moins de `rayon_km` d'une position : {"velo": n, "bus": n}."""
    dlat, dlon = rayon_km / KM_PAR_DEGRE_LAT, rayon_km / (111.32 * math.cos(math.radians(lat)))
    df = pd.read_sql(sa.text(
        "SELECT type, COUNT(*) AS n FROM lieu WHERE type IN ('station_velo', 'arret_bus') AND lat BETWEEN :lat1 AND :lat2 "
        "AND lon BETWEEN :lon1 AND :lon2 GROUP BY type"),
        engine, params={"lat1": lat - dlat, "lat2": lat + dlat, "lon1": lon - dlon, "lon2": lon + dlon})
    comptes = dict(zip(df["type"], df["n"]))
    return {"velo": int(comptes.get("station_velo", 0)), "bus": int(comptes.get("arret_bus", 0))}


def dernier_km(distance_km, proches):
    """(mode, détail) du dernier kilomètre selon la distance gare → destination et ce qu'on trouve près de la gare."""
    if distance_km is None:
        return "--", "Pas de gare proche connue"
    if distance_km <= SEUIL_PIED_KM:
        return "Marche à pied", f"environ {max(1, round(distance_km * 1000 / VITESSE_MARCHE_M_MIN))} min à pied"
    pres = f"{proches['velo']} station(s) vélo et {proches['bus']} arrêt(s) de bus à moins de {int(RAYON_ALENTOURS_KM * 1000)} m de la gare"
    if distance_km <= SEUIL_VELO_BUS_KM and (proches["velo"] or proches["bus"]):
        return "Vélo / Bus", pres
    return "Voiture / Taxi", pres if distance_km <= SEUIL_VELO_BUS_KM else f"plus de {int(SEUIL_VELO_BUS_KM)} km de la gare"


def pois_autour(engine, lat, lon, categorie="tous", rayon_km=RAYON_POI_KM, limite=MAX_POI):
    """Lieux de la catégorie à moins de `rayon_km` d'une position, les plus proches d'abord : DataFrame id, type, nom, lat, lon, distance_km."""
    dlat, dlon = rayon_km / KM_PAR_DEGRE_LAT, rayon_km / (111.32 * math.cos(math.radians(lat)))
    df = pd.read_sql(sa.text(
        "SELECT id, type, nom, lat, lon FROM lieu WHERE type IN :types AND lat BETWEEN :lat1 AND :lat2 AND lon BETWEEN :lon1 AND :lon2").bindparams(
        sa.bindparam("types", expanding=True)),
        engine, params={"types": list(_types(categorie)), "lat1": lat - dlat, "lat2": lat + dlat, "lon1": lon - dlon, "lon2": lon + dlon})
    df["distance_km"] = ((df["lat"] - lat) * KM_PAR_DEGRE_LAT) ** 2 + ((df["lon"] - lon) * 111.32 * math.cos(math.radians(lat))) ** 2
    df["distance_km"] = df["distance_km"].pow(0.5)
    return df[df["distance_km"] <= rayon_km].sort_values("distance_km").head(limite).reset_index(drop=True)


def quand_depuis(date, heure=None, maintenant=None):
    """Date (« AAAA-MM-JJ ») et heure (« HH:MM ») du formulaire → datetime. Sans heure : maintenant si la date est aujourd'hui, sinon 8 h."""
    maintenant = maintenant or datetime.now()
    jour = datetime.strptime(str(date)[:10], "%Y-%m-%d").date()
    if heure:
        h, m = str(heure).split(":")
        return datetime.combine(jour, time(int(h), int(m)))
    return maintenant.replace(microsecond=0) if jour == maintenant.date() else datetime.combine(jour, HEURE_DEFAUT)


def _trace(trajet, reseau, depart, arrivee):
    """(polylignes [[lat, lon], …], sur_voie) : une par train du trajet, collée aux voies. Sans trajet, la liaison directe entre les deux gares."""
    couples = [(s["de_lonlat"], s["vers_lonlat"]) for s in (trajet or {}).get("sections", [])
               if s["type"] == "public_transport" and s.get("de_lonlat") and s.get("vers_lonlat")] or [(depart, arrivee)]
    lignes, sur_voie = [], True
    for de, vers in couples:
        points, ok = chemin(reseau, de, vers)
        lignes.append([[lat, lon] for lon, lat in points])
        sur_voie = sur_voie and ok
    return lignes, sur_voie


def rechercher(depart_id, destination_id, quand=None, retour=None, categorie="tous", engine=None, reseau=None):
    """Prépare tout l'onglet pour un départ (id d'une gare) et une destination (id d'un lieu) : voir l'en-tête du module."""
    engine = engine or get_engine()
    depart, destination = _lieu(engine, depart_id), _lieu(engine, destination_id)
    if depart is None or destination is None:
        return None
    gare = _lieu(engine, destination["gare_proche_id"]) if destination["gare_proche_id"] else None
    distance = destination["distance_gare_km"]
    proches = alentours(engine, gare["lat"], gare["lon"]) if gare else {"velo": 0, "bus": 0}
    resultat = {"depart": depart, "destination": destination, "gare_arrivee": gare, "distance_km": distance, "alentours": proches,
                "dernier_km": dernier_km(distance, proches), "faisable": None if distance is None else distance <= SEUIL_VELO_BUS_KM,
                "trajets": [], "retour": None, "erreur_api": None, "trace": [], "sur_voie": False,
                "pois": pois_autour(engine, destination["lat"], destination["lon"], categorie)}
    if gare is None or not depart["code_uic"] or not gare["code_uic"]:
        return resultat
    try:
        resultat["trajets"] = navitia.itineraires(navitia.id_gare(depart["code_uic"]), navitia.id_gare(gare["code_uic"]), quand=quand, nombre=MAX_TRAJETS)
        if retour is not None:
            tous = navitia.itineraires(navitia.id_gare(gare["code_uic"]), navitia.id_gare(depart["code_uic"]), quand=retour, nombre=1)
            resultat["retour"] = tous[0] if tous else None
    except RuntimeError as erreur:
        resultat["erreur_api"] = str(erreur)
    resultat["trace"], resultat["sur_voie"] = _trace(resultat["trajets"][0] if resultat["trajets"] else None, reseau,
                                                     (depart["lon"], depart["lat"]), (gare["lon"], gare["lat"]))
    return resultat
