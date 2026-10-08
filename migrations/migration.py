"""Migration de la base : applique les migrations de migrations/versions/ jusqu'à la plus récente.

Usage :
    python migrations/migration.py                          # met la base à jour (001, puis 002 si elle existe…)
    python migrations/migration.py --new "ajoute X"    # crée la migration suivante (numéro = dernier + 1)
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from lib.db.connection import get_engine


def _config():
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    return cfg


def current_version():
    """Dernière migration appliquée à la base (None si la base est vide)."""
    with get_engine().connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def latest_version(cfg):
    return ScriptDirectory.from_config(cfg).get_current_head()


def migrate():
    cfg = _config()
    print(f"Base : version {current_version() or 'vide'} → cible {latest_version(cfg) or 'aucune migration'}")
    command.upgrade(cfg, "head")
    print(f"Base à jour : version {current_version()}")


def new(message):
    cfg = _config()
    versions = [int(r.revision) for r in ScriptDirectory.from_config(cfg).walk_revisions() if r.revision.isdigit()]
    numero = f"{max(versions, default=0) + 1:03d}"
    command.revision(cfg, message=message, autogenerate=True, rev_id=numero)
    print(f"Migration {numero} créée dans migrations/versions/ : à relire avant de l'appliquer.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--new", metavar="MESSAGE", help="crée la prochaine migration d'après lib/db/models.py")
    args = parser.parse_args()
    new(args.new) if args.new else migrate()
