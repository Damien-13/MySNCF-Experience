"""Migration de la base : applique les migrations de bdd/versions/ jusqu'à la plus récente.

Usage :
    python src/migration.py                          # met la base à jour (001, puis 002 si elle existe…)
    python src/migration.py --nouvelle "ajoute X"    # crée la migration suivante (numéro = dernier + 1)
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

from lib.bdd import get_engine


def _config():
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "bdd"))
    return cfg


def version_actuelle():
    """Dernière migration appliquée à la base (None si la base est vide)."""
    with get_engine().connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def derniere_version(cfg):
    return ScriptDirectory.from_config(cfg).get_current_head()


def migrer():
    cfg = _config()
    print(f"Base : version {version_actuelle() or 'vide'} → cible {derniere_version(cfg) or 'aucune migration'}")
    command.upgrade(cfg, "head")
    print(f"Base à jour : version {version_actuelle()}")


def nouvelle(message):
    cfg = _config()
    versions = [int(r.revision) for r in ScriptDirectory.from_config(cfg).walk_revisions() if r.revision.isdigit()]
    numero = f"{max(versions, default=0) + 1:03d}"
    command.revision(cfg, message=message, autogenerate=True, rev_id=numero)
    print(f"Migration {numero} créée dans bdd/versions/ : à relire avant de l'appliquer.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--nouvelle", metavar="MESSAGE", help="crée la prochaine migration d'après lib/modeles.py")
    args = parser.parse_args()
    nouvelle(args.nouvelle) if args.nouvelle else migrer()
