"""Transformation des stations de vélo statiques : nettoie le stationnement cyclable et les vélos en libre-service (Vélib', Vélo'v),
puis remplit lieu (type « station_velo ») et station_velo, avec la gare la plus proche.

Usage : python src/transformation/velo.py   (les gares doivent déjà être chargées : voir transformation.py)
Relançable sans risque : les stations vélo sont remplacées (tout passe ou rien).
La disponibilité en temps réel n'est pas stockée : voir lib/flux.py.

Quatre sources, une ligne par station ou par parking (lieu.source = nom de la source, station_velo.reseau = type de réseau) :
- velo_stationnement_osm : parkings à vélos d'OpenStreetMap (réseau « stationnement »)
- velo_stationnement_gares_centre_val_de_loire : parkings en gare de la région (réseau « stationnement »)
- vls_paris_velib : stations Vélib' (réseau « velib »)
- vls_lyon_velov : stations Vélo'v (réseau « velov »)

Chevauchement : la région et OpenStreetMap décrivent les mêmes parkings en gare (98 % des parkings de la région ont un parking
OpenStreetMap à moins de 25 m, pour 3 285 places contre 3 129). Règle de gestion : la source officielle de la région prime, et les parkings
OpenStreetMap à moins de RAYON_CHEVAUCHEMENT_M mètres d'un de ses parkings sont écartés. Pas de rapprochement pour Vélib' et Vélo'v (des bornes
de libre-service, pas des parkings) ni à l'intérieur d'OpenStreetMap (des arceaux voisins, rarement de même capacité, pas des copies).

Nettoyage : sans position valide, hors de la France continentale (étranger, Corse, outre-mer) ou en double dans sa source : écarté.
Une capacité manquante ou nulle est laissée vide.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import sqlalchemy as sa

from geo import a_proximite, dans_la_france_continentale, en_france_continentale
from lib.db.connection import get_engine
from lib.db.models import Lieu, StationVelo
from lieux import inserer, lignes_lieu, lire_gares, rattacher_aux_gares

DATA = ROOT / "data"
TYPE = "station_velo"
REGION = "velo_stationnement_gares_centre_val_de_loire"
OSM = "velo_stationnement_osm"
RAYON_CHEVAUCHEMENT_M = 25
COLONNES = ["nom", "commune", "departement", "lat", "lon", "reseau", "capacite", "source"]


def _lire(dossier, fichier, **options):
    return pd.read_csv(DATA / dossier / fichier, dtype=str, **options)


def _lon_lat(texte):
    """« [lon,lat] » → (lon, lat)."""
    xy = texte.str.extract(r"^\s*\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\]\s*$").astype(float)
    return xy[0], xy[1]


def _standard(source, reseau, nom, commune, code_insee, lat, lon, capacite):
    """Les colonnes communes à toutes les sources. Département = deux premiers chiffres du code INSEE de la commune."""
    capacite = pd.to_numeric(capacite, errors="coerce")
    return pd.DataFrame({
        "nom": nom, "commune": commune,
        "departement": pd.Series(code_insee).str.strip().str[:2],
        "lat": pd.to_numeric(lat, errors="coerce"), "lon": pd.to_numeric(lon, errors="coerce"),
        "reseau": reseau, "capacite": capacite.where(capacite > 0), "source": source,
    })[COLONNES]


def stationnement(df, source):
    """Fichiers au schéma « Stationnement cyclable » (OpenStreetMap, gares du Centre-Val de Loire)."""
    lon, lat = _lon_lat(df["coordonneesxy"])
    out = _standard(source, "stationnement", None, None, df["code_com"], lat, lon, df["capacite"])
    if "id_osm" in df:
        doublon = df["id_osm"].notna() & df["id_osm"].duplicated()      # un même nœud OpenStreetMap n'est compté qu'une fois
        out = out[~doublon]                                             # (un identifiant vide n'est pas un doublon)
    return out


def velib(df):
    lat_lon = df["Coordonnées géographiques"].str.extract(r"^\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*$").astype(float)
    return _standard("vls_paris_velib", "velib", df["Nom station"].str.strip(), df["Nom communes équipées"].str.strip(),
                     df["Code INSEE communes équipées"], lat_lon[0], lat_lon[1], df["Capacité de la station"])


def velov(df):
    return _standard("vls_lyon_velov", "velov", df["name"].str.replace(r"^\d+\s*-\s*", "", regex=True).str.strip(),
                     df["commune"].str.strip(), df["code_insee"], df["lat"], df["lng"], df["bike_stands"])


def nettoyer(stations):
    """Écarte ce qui est hors de la France continentale ou sans position, et les doublons exacts d'une même source."""
    valides = (stations["lat"].notna() & stations["lon"].notna() & dans_la_france_continentale(stations["lat"], stations["lon"])
               & (stations["departement"].isna() | en_france_continentale(stations["departement"].fillna("00"))))
    return stations[valides].drop_duplicates(["source", "lat", "lon", "nom", "capacite"]).reset_index(drop=True)


def ecarter_chevauchements(stations):
    """Écarte les parkings OpenStreetMap qui doublonnent un parking de la région (voir la règle en tête de fichier)."""
    region = stations[stations["source"] == REGION]
    osm = stations["source"] == OSM
    doublon = osm & a_proximite(stations["lat"], stations["lon"], region["lat"], region["lon"], RAYON_CHEVAUCHEMENT_M)
    return stations[~doublon].reset_index(drop=True)


def lire():
    """Les quatre sources, au même format. Retourne (stations, nombre de lignes lues)."""
    brutes = [
        (_lire("velo_stationnement_osm", "data.csv", sep=";"), lambda d: stationnement(d, "velo_stationnement_osm")),
        (_lire("velo_stationnement_gares_centre_val_de_loire", "data.csv", sep=";", encoding="utf-8-sig"),
         lambda d: stationnement(d, "velo_stationnement_gares_centre_val_de_loire")),
        (_lire("vls_paris_velib", "velib-disponibilite-en-temps-reel.csv", sep=";", encoding="utf-8-sig"), velib),
        (_lire("vls_lyon_velov", "jcd_jcdecaux.jcdvelov"), velov),
    ]
    return pd.concat([transformer(df) for df, transformer in brutes], ignore_index=True), sum(len(df) for df, _ in brutes)


def charger(stations, engine=None):
    """Remplace en une transaction les stations vélo (lieu et station_velo). `stations` : colonnes de lieu + reseau, capacite.
    Retourne leur nombre."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        anciens = sa.select(Lieu.id).where(Lieu.type == TYPE)
        conn.execute(sa.delete(StationVelo).where(StationVelo.lieu_id.in_(anciens)))
        conn.execute(sa.delete(Lieu).where(Lieu.type == TYPE))
        premier = (conn.scalar(sa.select(sa.func.max(Lieu.id))) or 0) + 1
        ids = list(range(premier, premier + len(stations)))
        lieux = stations.drop(columns=["reseau", "capacite", "source"]).assign(id=ids)
        lignes = lignes_lieu(lieux, TYPE, None)
        for ligne, source in zip(lignes, stations["source"]):
            ligne["source"] = source
        inserer(conn, Lieu, lignes)
        capacites = stations["capacite"].astype(object).where(stations["capacite"].notna(), None)
        inserer(conn, StationVelo, [{"lieu_id": i, "reseau": r, "capacite": None if c is None else int(c)}
                                    for i, r, c in zip(ids, stations["reseau"], capacites)])
    return len(stations)


def transformer():
    brut, lues = lire()
    propres = nettoyer(brut)
    stations = ecarter_chevauchements(propres)
    gares = lire_gares()
    if gares.empty:
        sys.exit("Aucune gare en base : lancer d'abord l'étape gares (python src/transformation/transformation.py)")
    nb = charger(rattacher_aux_gares(stations, gares))
    print(f"Vélo : {nb} stations chargées ({lues - len(propres)} écartées sur {lues} : hors France continentale, doublons ou position invalide ; "
          f"{len(propres) - nb} parkings OpenStreetMap écartés car déjà dans le fichier de la région)")
    return nb


if __name__ == "__main__":
    transformer()
