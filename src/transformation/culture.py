"""Transformation de la culture : nettoie basilic, puis remplit lieu (type « culture ») avec la gare la plus proche.

Usage : python src/transformation/culture.py   (les gares doivent déjà être chargées : voir transformation.py)
Relançable sans risque : les lieux de la source sont remplacés (tout passe ou rien).

Nettoyage :
- Hors métropole écarté (départements 97x et 98x, ou sans département comme les lieux à l'étranger) : le dashboard couvre la France métropolitaine.
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
import sqlalchemy as sa

from geo import plus_proche
from lib.db.connection import get_engine
from lib.db.models import Lieu

SOURCE = "basilic"
FICHIER = ROOT / "data" / "basilic" / "base-des-lieux-et-des-equipements-culturels.csv"
PAQUET_INSERT = 10_000


def _lire(fichier):
    return pd.read_csv(fichier, sep=";", encoding="utf-8-sig", dtype=str, low_memory=False)


def nettoyer(df):
    """Une ligne par lieu culturel de métropole : nom, adresse, commune, departement, lat, lon."""
    departement = df["N_Département"].str.strip()
    out = pd.DataFrame({
        "nom": df["Nom"].str.strip(),
        "adresse": df["Adresse"].str.strip(),
        "commune": df["libelle_geographique"].str.strip(),
        "departement": departement,
        "lat": pd.to_numeric(df["Latitude"], errors="coerce"),
        "lon": pd.to_numeric(df["Longitude"], errors="coerce"),
    })
    metropole = departement.fillna("").ne("") & ~departement.fillna("").str.match(r"^9[78]")
    valides = out["nom"].fillna("").ne("") & out["lat"].between(-90, 90) & out["lon"].between(-180, 180)
    return out[metropole & valides].drop_duplicates(["nom", "adresse", "lat", "lon"]).reset_index(drop=True)


def rattacher_aux_gares(lieux, gares):
    """Ajoute gare_proche_id et distance_gare_km. `gares` : DataFrame id, lat, lon (vide = colonnes vides)."""
    indices, distances = plus_proche(lieux["lat"], lieux["lon"], gares["lat"], gares["lon"])
    ids = gares["id"].to_numpy()
    out = lieux.copy()
    out["gare_proche_id"] = [int(ids[i]) if i >= 0 else None for i in indices]
    out["distance_gare_km"] = distances.round(3)
    return out


def charger(lieux, engine=None):
    """Remplace en une transaction les lieux de la source. Retourne leur nombre."""
    engine = engine or get_engine()
    lignes = lieux.astype(object).where(lieux.notna(), None).to_dict("records")
    for ligne in lignes:
        ligne.update(type="culture", source=SOURCE)
    with engine.begin() as conn:
        conn.execute(sa.delete(Lieu).where(Lieu.type == "culture", Lieu.source == SOURCE))
        for i in range(0, len(lignes), PAQUET_INSERT):
            conn.execute(sa.insert(Lieu), lignes[i:i + PAQUET_INSERT])
    return len(lignes)


def lire_gares(engine=None):
    """Gares déjà chargées : id, lat, lon."""
    engine = engine or get_engine()
    requete = sa.select(Lieu.id, Lieu.lat, Lieu.lon).where(Lieu.type == "gare")
    with engine.connect() as conn:
        return pd.DataFrame(conn.execute(requete).all(), columns=["id", "lat", "lon"])


def transformer():
    brut = _lire(FICHIER)
    lieux = nettoyer(brut)
    gares = lire_gares()
    if gares.empty:
        sys.exit("Aucune gare en base : lancer d'abord l'étape gares (python src/transformation/transformation.py)")
    nb = charger(rattacher_aux_gares(lieux, gares))
    print(f"Culture : {nb} lieux chargés ({len(brut) - nb} écartés sur {len(brut)} : hors métropole, doublons ou position invalide)")
    return nb


if __name__ == "__main__":
    transformer()
