"""Vérifie l'initialisation (src/initialize.py) sur une base SQLite temporaire, supprimée à la fin."""
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "migrations"))

from sqlalchemy import inspect

import initialize
from lib.db.connection import get_engine
from lib.db.models import Base


@pytest.fixture
def db_path(monkeypatch):
    """Chemin d'un fichier SQLite dans un dossier qui n'existe pas encore."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "nouveau_dossier" / "test.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
        yield path


def test_initialize_creates_database_and_folder(db_path):
    initialize.initialize()
    assert db_path.is_file()
    assert set(Base.metadata.tables) <= set(inspect(get_engine()).get_table_names())


def test_initialize_can_be_rerun(db_path):
    initialize.initialize()
    initialize.initialize()
    assert set(Base.metadata.tables) <= set(inspect(get_engine()).get_table_names())


def test_initialize_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit):
        initialize.create_database()


def test_initialize_downloads_the_listed_sources(db_path, monkeypatch):
    asked = []
    monkeypatch.setattr(initialize, "SOURCES", ["gares_voyageurs"])
    monkeypatch.setattr(initialize, "download", asked.append)
    initialize.initialize()
    assert asked == [["gares_voyageurs"]]


def test_initialize_rejects_source_without_url(db_path, monkeypatch):
    monkeypatch.setattr(initialize, "SOURCES", ["DATASET_BASILIC_URL"])      # nom complet au lieu du nom court
    with pytest.raises(SystemExit):
        initialize.initialize()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
