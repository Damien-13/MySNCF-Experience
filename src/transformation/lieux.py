"""Outils communs aux étapes qui remplissent la table lieu (culture, tourisme, événements) : gares, rattachement, chargement."""
import pandas as pd
import sqlalchemy as sa

from geo import plus_proche
from lib.db.connection import get_engine
from lib.db.models import Lieu

PAQUET_INSERT = 10_000


def lire_gares(engine=None):
    """Gares déjà chargées : id, lat, lon."""
    engine = engine or get_engine()
    requete = sa.select(Lieu.id, Lieu.lat, Lieu.lon).where(Lieu.type == "gare")
    with engine.connect() as conn:
        return pd.DataFrame(conn.execute(requete).all(), columns=["id", "lat", "lon"])


def rattacher_aux_gares(lieux, gares):
    """Ajoute gare_proche_id et distance_gare_km (à vol d'oiseau). `gares` : DataFrame id, lat, lon (vide = colonnes vides)."""
    indices, distances = plus_proche(lieux["lat"], lieux["lon"], gares["lat"], gares["lon"])
    ids = gares["id"].to_numpy()
    out = lieux.copy()
    out["gare_proche_id"] = [int(ids[i]) if i >= 0 else None for i in indices]
    out["distance_gare_km"] = distances.round(3)
    return out


def lignes_lieu(lieux, type_, source):
    """Liste de dicts prête à insérer dans lieu (NaN → None, type et source ajoutés)."""
    lignes = lieux.astype(object).where(lieux.notna(), None).to_dict("records")
    for ligne in lignes:
        ligne.update(type=type_, source=source)
    return lignes


def inserer(conn, modele, lignes):
    for i in range(0, len(lignes), PAQUET_INSERT):
        conn.execute(sa.insert(modele), lignes[i:i + PAQUET_INSERT])


def charger(lieux, type_, source, engine=None):
    """Remplace en une transaction les lieux de ce type et de cette source. Retourne leur nombre."""
    engine = engine or get_engine()
    lignes = lignes_lieu(lieux, type_, source)
    with engine.begin() as conn:
        conn.execute(sa.delete(Lieu).where(Lieu.type == type_, Lieu.source == source))
        inserer(conn, Lieu, lignes)
    return len(lignes)
