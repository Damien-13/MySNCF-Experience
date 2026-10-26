"""Purge des données brutes : supprime les dossiers sources de data/ une fois tout chargé dans la base.

Appelée à la fin de src/initialize.py. Ne supprime rien si une table de la base est vide (chargement incomplet).
Le fichier de la base SQLite et le .gitkeep ne sont jamais touchés : seuls les dossiers des sources sont supprimés.
Pour garder les données brutes, mettre PURGE_DONNEES=0 dans le .env.
"""
import os
import shutil
from pathlib import Path

from sqlalchemy import func, select

from lib.db.connection import get_engine
from lib.db.models import Base


def tables_vides(engine):
    """Noms des tables du schéma qui ne contiennent aucune ligne."""
    with engine.connect() as connexion:
        return [nom for nom, table in Base.metadata.tables.items()
                if not connexion.execute(select(func.count()).select_from(table)).scalar()]


def purger(data_dir, sources):
    """Supprime data_dir/<source> pour chaque source si toutes les tables sont remplies. Retourne les octets libérés (0 si rien n'est purgé)."""
    if os.environ.get("PURGE_DONNEES", "1") == "0":
        print("Purge : désactivée (PURGE_DONNEES=0), données brutes gardées")
        return 0
    vides = tables_vides(get_engine())
    if vides:
        print(f"Purge : annulée, tables vides dans la base : {vides}. Données brutes gardées")
        return 0
    libere = 0
    for source in sources:
        dossier = Path(data_dir) / source
        if dossier.is_dir() and not dossier.is_symlink():
            libere += sum(f.stat().st_size for f in dossier.rglob("*") if f.is_file() and not f.is_symlink())
            shutil.rmtree(dossier)
    print(f"Purge : {libere / 1e9:.1f} Go de données brutes supprimés, la base est gardée")
    return libere
