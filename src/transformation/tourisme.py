"""Transformation du tourisme : nettoie DATAtourisme (place), puis remplit lieu (type « tourisme ») avec la gare la plus proche.

Usage : python src/transformation/tourisme.py   (les gares doivent déjà être chargées : voir transformation.py)
Relançable sans risque : les lieux de la source sont remplacés (tout passe ou rien).

Nettoyage :
- Seules les attractions sont gardées (ATTRACTIONS) : hébergements, restaurants, commerces et services sont écartés.
- Doublons d'identifiant DATAtourisme supprimés ; sans nom ou hors du rectangle de la France continentale écartés
  (outre-mer, étranger, positions aberrantes) ; Corse écartée.
- Département et commune déduits de « code postal#commune ».
Transformation : gare_proche_id et distance_gare_km (à vol d'oiseau) calculés pour chaque lieu.
Lecture par paquets : le fichier pèse plus de 250 Mo.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

import lieux as lieux_communs
from geo import dans_la_france_continentale, departement_et_commune, en_france_continentale
from lieux import lire_gares, rattacher_aux_gares

SOURCE = "datatourisme_place"
FICHIER = ROOT / "data" / "datatourisme_place" / "datatourisme-place.csv"
COLONNES = ["Nom_du_POI", "Categories_de_POI", "Latitude", "Longitude", "Adresse_postale", "Code_postal_et_commune", "URI_ID_du_POI"]
PAQUET_LECTURE = 50_000

# Catégories DATAtourisme qui font une attraction (le fichier contient aussi hébergements, restauration, commerces…)
ATTRACTIONS = r"[#/](?:CulturalSite|NaturalHeritage|SportsAndLeisurePlace|ParkAndGarden|Landform)(?:\||$)"


def lire(fichier=FICHIER):
    """Lit le CSV par paquets et ne garde que les attractions. Retourne (lignes gardées, nombre de lignes lues)."""
    gardes, lues = [], 0
    for paquet in pd.read_csv(fichier, dtype=str, usecols=COLONNES, chunksize=PAQUET_LECTURE):
        lues += len(paquet)
        gardes.append(paquet[paquet["Categories_de_POI"].fillna("").str.contains(ATTRACTIONS, regex=True)])
    return pd.concat(gardes, ignore_index=True), lues


def nettoyer(df):
    """Une ligne par attraction : nom, adresse, commune, departement, lat, lon."""
    departement, commune = departement_et_commune(df["Code_postal_et_commune"])
    out = pd.DataFrame({
        "uri": df["URI_ID_du_POI"],
        "nom": df["Nom_du_POI"].str.strip(),
        "adresse": df["Adresse_postale"].str.strip(),
        "commune": commune,
        "departement": departement,
        "lat": pd.to_numeric(df["Latitude"], errors="coerce"),
        "lon": pd.to_numeric(df["Longitude"], errors="coerce"),
    })
    valides = (out["nom"].fillna("").ne("") & en_france_continentale(out["departement"])
               & dans_la_france_continentale(out["lat"], out["lon"]))
    out = out[valides].drop_duplicates("uri")
    return out.drop(columns="uri").drop_duplicates(["nom", "adresse", "lat", "lon"]).reset_index(drop=True)


def charger(lieux, engine=None):
    """Remplace en une transaction les lieux de la source. Retourne leur nombre."""
    return lieux_communs.charger(lieux, "tourisme", SOURCE, engine)


def transformer():
    brut, lues = lire()
    lieux = nettoyer(brut)
    gares = lire_gares()
    if gares.empty:
        sys.exit("Aucune gare en base : lancer d'abord l'étape gares (python src/transformation/transformation.py)")
    nb = charger(rattacher_aux_gares(lieux, gares))
    print(f"Tourisme : {nb} attractions chargées (sur {lues} lignes : {lues - len(brut)} hors attractions, "
          f"{len(brut) - nb} écartées : doublons, hors France continentale ou position invalide)")
    return nb


if __name__ == "__main__":
    transformer()
