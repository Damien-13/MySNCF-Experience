"""Transformation de la culture : nettoie basilic, puis remplit lieu (type « culture ») avec la gare la plus proche.

Usage : python src/transformation/culture.py   (les gares doivent déjà être chargées : voir transformation.py)
Relançable sans risque : les lieux de la source sont remplacés (tout passe ou rien).

Nettoyage :
- Hors France continentale écarté (outre-mer 97x et 98x, Corse 2A et 2B, ou sans département comme les lieux à l'étranger).
- Lieux sans nom ou sans position valide écartés ; doublons exacts (nom, adresse, position) supprimés.
- Département : N_Département (« 01 », « 2A »), comme pour les gares.
Transformation : gare_proche_id et distance_gare_km (à vol d'oiseau) calculés pour chaque lieu.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

import lieux as lieux_communs
from geo import en_france_continentale
from lieux import lire_gares, rattacher_aux_gares

SOURCE = "basilic"
FICHIER = ROOT / "data" / "basilic" / "base-des-lieux-et-des-equipements-culturels.csv"


def _lire(fichier):
    return pd.read_csv(fichier, sep=";", encoding="utf-8-sig", dtype=str, low_memory=False)


def nettoyer(df):
    """Une ligne par lieu culturel de France continentale : nom, adresse, commune, departement, lat, lon."""
    departement = df["N_Département"].str.strip()
    out = pd.DataFrame({
        "nom": df["Nom"].str.strip(),
        "adresse": df["Adresse"].str.strip(),
        "commune": df["libelle_geographique"].str.strip(),
        "departement": departement,
        "lat": pd.to_numeric(df["Latitude"], errors="coerce"),
        "lon": pd.to_numeric(df["Longitude"], errors="coerce"),
    })
    metropole = en_france_continentale(departement)
    valides = out["nom"].fillna("").ne("") & out["lat"].between(-90, 90) & out["lon"].between(-180, 180)
    return out[metropole & valides].drop_duplicates(["nom", "adresse", "lat", "lon"]).reset_index(drop=True)


def charger(lieux, engine=None):
    """Remplace en une transaction les lieux de la source. Retourne leur nombre."""
    return lieux_communs.charger(lieux, "culture", SOURCE, engine)


def transformer():
    brut = _lire(FICHIER)
    lieux = nettoyer(brut)
    gares = lire_gares()
    if gares.empty:
        sys.exit("Aucune gare en base : lancer d'abord l'étape gares (python src/transformation/transformation.py)")
    nb = charger(rattacher_aux_gares(lieux, gares))
    print(f"Culture : {nb} lieux chargés ({len(brut) - nb} écartés sur {len(brut)} : hors France continentale, doublons ou position invalide)")
    return nb


if __name__ == "__main__":
    transformer()
