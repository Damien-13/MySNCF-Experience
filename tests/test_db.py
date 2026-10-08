"""Vérifie que la base se crée avec Alembic (SQLite temporaire, supprimée à la fin) et correspond aux modèles."""
import sys
import tempfile
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "migrations"))

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

import migration
from lib.db.connection import get_engine
from lib.db.models import Base, Evenement, EvenementLieu, EvenementPeriode, Gare, Lieu


@pytest.fixture
def base(monkeypatch):
    """Pointe DATABASE_URL vers un fichier SQLite temporaire, supprimé après le test."""
    with tempfile.TemporaryDirectory() as dossier:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{dossier}/test.db")
        yield


def test_migration_creates_all_tables(base):
    migration.migrate()
    tables = set(inspect(get_engine()).get_table_names())
    assert set(Base.metadata.tables) <= tables


def test_migration_reaches_latest_version(base):
    migration.migrate()
    assert migration.current_version() == migration.latest_version(migration._config())


def test_rerunning_migration_changes_nothing(base):
    migration.migrate()
    version = migration.current_version()
    migration.migrate()
    assert migration.current_version() == version


def test_migrations_match_models(base):
    """Si ce test échoue : lib/db/models.py a changé sans nouvelle migration (python migrations/migration.py --new "...")."""
    migration.migrate()
    with get_engine().connect() as conn:
        ecarts = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert ecarts == []


def test_write_and_read(base):
    """Une gare, un lieu d'événement et leurs liens s'enregistrent et se relisent."""
    migration.migrate()
    with Session(get_engine()) as s:
        gare = Lieu(type="gare", nom="Toulon", lat=43.128, lon=5.93)
        s.add(gare)
        s.flush()
        s.add(Gare(lieu_id=gare.id, code_uic="87000000"))
        salle = Lieu(type="evenement", nom="Salle test", gare_proche_id=gare.id, distance_gare_km=0.8)
        evt = Evenement(nom="Concert test")
        s.add_all([salle, evt])
        s.flush()
        s.add_all([EvenementLieu(evenement_id=evt.id, lieu_id=salle.id),
                   EvenementPeriode(evenement_id=evt.id, date_debut=date(2026, 11, 1), date_fin=date(2026, 11, 2))])
        s.commit()

    with Session(get_engine()) as s:
        proche = s.scalar(select(Lieu).where(Lieu.nom == "Salle test")).gare_proche_id
        assert s.get(Lieu, proche).nom == "Toulon"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
