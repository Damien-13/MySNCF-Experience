"""Vérifie la purge des données brutes (src/purge.py) sur une base SQLite temporaire, supprimée à la fin."""
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "migrations"))

import migration
import purge
from lib.db.connection import get_engine
from lib.db.models import Base


@pytest.fixture
def dossier(monkeypatch):
    """Dossier data/ temporaire avec deux sources et une base migrée, mais vide."""
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{data / 'test.db'}")
        monkeypatch.delenv("PURGE_DONNEES", raising=False)
        migration.migrate()
        for source in ("a", "b"):
            (data / source).mkdir()
            (data / source / "x.csv").write_text("1,2,3")
        (data / ".gitkeep").write_text("")
        yield data


def base_remplie(monkeypatch):
    """Fait croire à la purge que chaque table a des lignes."""
    monkeypatch.setattr(purge, "tables_vides", lambda engine: [])


def test_purge_removes_sources_when_database_is_full(dossier, monkeypatch):
    base_remplie(monkeypatch)
    assert purge.purger(dossier, ["a", "b"]) == 10
    assert not (dossier / "a").exists() and not (dossier / "b").exists()
    assert (dossier / "test.db").is_file() and (dossier / ".gitkeep").is_file()


def test_tables_vides_lists_every_table_of_an_empty_database(dossier):
    assert set(purge.tables_vides(get_engine())) == set(Base.metadata.tables)


def test_purge_keeps_everything_when_a_table_is_empty(dossier):
    assert purge.purger(dossier, ["a", "b"]) == 0
    assert (dossier / "a" / "x.csv").is_file()


def test_purge_can_be_disabled(dossier, monkeypatch):
    base_remplie(monkeypatch)
    monkeypatch.setenv("PURGE_DONNEES", "0")
    assert purge.purger(dossier, ["a"]) == 0
    assert (dossier / "a" / "x.csv").is_file()


def test_purge_ignores_missing_source(dossier, monkeypatch):
    base_remplie(monkeypatch)
    purge.purger(dossier, ["absente"])
    assert (dossier / "a").is_dir()
