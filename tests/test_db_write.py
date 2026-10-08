"""Vérifie insert, update et delete (lib/db/write.py) sur une base SQLite temporaire, supprimée à la fin."""
import sys
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "migrations"))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import migration
from lib.db.connection import get_engine
from lib.db.models import Evenement, EvenementPeriode, Lieu
from lib.db.write import delete, insert, update


@pytest.fixture
def db(monkeypatch):
    """Base SQLite temporaire, migrée jusqu'à la dernière version, supprimée après le test."""
    with tempfile.TemporaryDirectory() as folder:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{folder}/test.db")
        migration.migrate()
        yield


def count(model):
    with Session(get_engine()) as s:
        return s.scalar(select(func.count()).select_from(model))


def test_insert_dataframe_with_missing_values_and_extra_column(db):
    df = pd.DataFrame({"type": ["gare", "culture"], "nom": ["Toulon", None], "lat": [43.1, float("nan")], "inconnue": [1, 2]})
    assert insert(Lieu, df) == 2
    with Session(get_engine()) as s:
        row = s.scalar(select(Lieu).where(Lieu.type == "culture"))
        assert row.nom is None and row.lat is None


def test_insert_list_of_dicts(db):
    assert insert(Lieu, [{"type": "gare", "nom": "A"}, {"type": "gare", "nom": "B"}]) == 2
    assert count(Lieu) == 2


def test_insert_by_chunks(db, monkeypatch):
    monkeypatch.setattr("lib.db.write.CHUNK_SIZE", 3)
    assert insert(Lieu, [{"type": "gare", "nom": str(i)} for i in range(10)]) == 10
    assert count(Lieu) == 10


def test_insert_dates_from_dataframe(db):
    insert(Evenement, [{"id": 1, "nom": "Concert"}])
    df = pd.DataFrame({"evenement_id": [1], "date_debut": pd.to_datetime(["2026-11-01"]), "date_fin": ["2026-11-02"]})
    insert(EvenementPeriode, df)
    with Session(get_engine()) as s:
        assert s.scalar(select(EvenementPeriode.date_debut)) == date(2026, 11, 1)


def test_insert_is_all_or_nothing(db):
    with pytest.raises(Exception):
        insert(Lieu, [{"id": 1, "type": "gare"}, {"id": 1, "type": "gare"}])   # même clé deux fois
    assert count(Lieu) == 0


def test_update_only_matching_rows(db):
    insert(Lieu, [{"id": 1, "type": "gare", "commune": "A"}, {"id": 2, "type": "gare", "commune": "A"}])
    assert update(Lieu, {"commune": "Toulon"}, {"id": 1}) == 1
    with Session(get_engine()) as s:
        assert s.get(Lieu, 1).commune == "Toulon" and s.get(Lieu, 2).commune == "A"


def test_delete_only_matching_rows(db):
    insert(Lieu, [{"type": "gare", "source": "x"}, {"type": "gare", "source": "x"}, {"type": "gare", "source": "y"}])
    assert delete(Lieu, {"source": "x"}) == 2
    assert count(Lieu) == 1


def test_filter_is_mandatory(db):
    insert(Lieu, [{"type": "gare"}])
    with pytest.raises(ValueError):
        delete(Lieu, {})
    with pytest.raises(ValueError):
        update(Lieu, {"nom": "x"}, None)
    assert count(Lieu) == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
