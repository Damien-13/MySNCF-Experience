"""Initialisation du projet : crée la base de données, puis télécharge les données nécessaires.

Usage : python src/initialize.py
Relançable sans risque (base déjà à jour = rien à faire). Pas de saisie au clavier et tout vient du .env,
pour pouvoir le lancer tel quel au démarrage d'un conteneur Docker.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "migrations"))

from sqlalchemy.engine import make_url

import migration
from lib.downloader import download

# Sources nécessaires à l'application (noms des DATASET_<SOURCE>_URL du .env). À compléter une fois les besoins identifiés.
SOURCES = []


def create_database():
    """Crée la base à la dernière version du schéma (pour SQLite : le fichier et son dossier si besoin)."""
    if "DATABASE_URL" not in os.environ:
        sys.exit("DATABASE_URL absent : copier .env.example en .env")
    url = make_url(os.environ["DATABASE_URL"])
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    migration.migrate()


def download_data():
    """Télécharge les sources nécessaires (rien tant que SOURCES est vide)."""
    if not SOURCES:
        print("Données : aucune source à télécharger pour l'instant (SOURCES vide dans src/initialize.py)")
        return
    download(SOURCES)


def initialize():
    os.chdir(ROOT)               # les chemins relatifs du .env (data/…) partent de la racine du projet
    create_database()
    download_data()


if __name__ == "__main__":
    initialize()
