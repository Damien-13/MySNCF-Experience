"""Initialisation du projet : crée la base de données, télécharge les données nécessaires, puis les nettoie et les charge dans la base.

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
sys.path.insert(0, str(ROOT / "src" / "transformation"))

from sqlalchemy.engine import make_url

import migration
import transformation
from lib.downloader import download

# Sources nécessaires à l'application : le nom court, sans DATASET_ ni _URL (« basilic » pour DATASET_BASILIC_URL du .env).
# Ce sont celles que lit la transformation (src/transformation/) : en ajouter une avec son étape.
DATA = ROOT / "data"
SOURCES = ["gares_voyageurs", "horaires_gares", "basilic", "datatourisme_place", "datatourisme_fma", "festivals",
           "velo_stationnement_osm", "velo_stationnement_gares_centre_val_de_loire", "vls_paris_velib", "vls_lyon_velov",
           "formes_voies_rfn", "formes_lignes_rfn", "osm_france", "horaires_sncf_gtfs", "transilien", "eurostar", "renfe_ave", "trenitalia_france", "idfm",
           *sorted(f"bus_{r}" for r in ["marseille_amp", "toulouse_tisseo", "bordeaux_tbm", "nantes_naolib", "strasbourg_cts", "rennes_star", "lille_ilevia", "nice_lignes_dazur", "rouen_astuce", "toulon_mistral", "angers_irigo", "tours_fil_bleu", "clermont_t2c", "orleans_tao", "dijon_divia", "brest_bibus", "besancon_ginko", "metz_le_met", "reims_grand_reims", "saint_etienne_stas", "montpellier_tam"])]


def create_database():
    """Crée la base à la dernière version du schéma (pour SQLite : le fichier et son dossier si besoin)."""
    if "DATABASE_URL" not in os.environ:
        sys.exit("DATABASE_URL absent : copier .env.example en .env")
    url = make_url(os.environ["DATABASE_URL"])
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    migration.migrate()


def download_data():
    """Télécharge les sources nécessaires qui ne sont pas déjà dans data/<source>/ (pour ne pas retélécharger des centaines de Mo)."""
    unknown = [s for s in SOURCES if f"DATASET_{s.upper()}_URL" not in os.environ]
    if unknown:
        sys.exit(f"Source sans URL dans le .env : {unknown} (attendu : DATASET_<SOURCE>_URL, nom court dans SOURCES, ex. 'basilic')")
    missing = [s for s in SOURCES if not any((DATA / s).glob("*"))]
    if missing:
        download(missing)
    print(f"Données : {len(SOURCES) - len(missing)} source(s) déjà présente(s), {len(missing)} téléchargée(s)")


def load_data():
    """Nettoie les données téléchargées et les charge dans la base (src/transformation/transformation.py)."""
    transformation.transformer()


def initialize():
    os.chdir(ROOT)               # les chemins relatifs du .env (data/…) partent de la racine du projet
    create_database()
    download_data()
    load_data()


if __name__ == "__main__":
    initialize()
