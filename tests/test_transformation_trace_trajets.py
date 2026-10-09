"""Vérifie le tracé des trajets (src/transformation/trace_trajets.py) sur un petit réseau synthétique et une base SQLite temporaire."""
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "migrations"))
sys.path.insert(0, str(ROOT / "src" / "transformation"))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import migration
import trace_trajets
from lib.db.connection import get_engine
from lib.db.models import Arret, Reseau, TraceTrajet

# Deux tronçons bout à bout (le trou de 100 m entre eux est raccordé), puis un tronçon isolé loin de tout.
RESEAU = [
    [[2.0, 48.0], [2.05, 48.0], [2.1, 48.0]],
    [[2.1009, 48.0], [2.15, 48.0], [2.2, 48.0]],
    [[5.0, 45.0], [5.1, 45.0]],
]
ARRETS = pd.DataFrame({
    "lon": [2.0, 2.2, 5.0, 2.0, 9.0],
    "lat": [48.0001, 48.0001, 45.0001, 48.5, 40.0],
}, index=["a", "b", "c", "d", "etranger"])


@pytest.fixture
def reseau():
    return trace_trajets.construire_reseau(RESEAU)


def _tracer(reseau, paires):
    paires = pd.DataFrame(paires, columns=["depart", "arrivee"])
    return {(t["arret_depart_id"], t["arret_arrivee_id"]): t for t in trace_trajets.tracer(*reseau, ARRETS, paires)}


def test_chemin_sur_les_voies_a_travers_le_raccord(reseau):
    t = _tracer(reseau, [("a", "b")])[("a", "b")]
    assert t["sur_voie"]
    points = json.loads(t["geometrie"])
    assert points[0] == [2.0, 48.0001] and points[-1] == [2.2, 48.0001]          # part et finit à la position des arrêts
    assert [2.15, 48.0] in points and [2.05, 48.0] in points                     # passe par les voies
    assert t["longueur_km"] == pytest.approx(14.9, abs=0.3)


def test_repli_en_ligne_droite_sans_chemin_ou_hors_reseau(reseau):
    traces = _tracer(reseau, [("a", "c"), ("a", "etranger"), ("a", "d")])
    assert not any(t["sur_voie"] for t in traces.values())                       # c est sur un tronçon isolé, etranger et d sont loin de tout
    assert all(len(json.loads(t["geometrie"])) == 2 for t in traces.values())    # ligne droite : deux points


def test_charger_remplace_tous_les_traces(monkeypatch):
    with tempfile.TemporaryDirectory() as dossier:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{dossier}/test.db")
        migration.migrate()
        engine = get_engine()
        with Session(engine) as session:
            session.add(Reseau(id="r", nom="R", mode="train"))
            session.add_all([Arret(id="a", reseau_id="r", nom="A"), Arret(id="b", reseau_id="r", nom="B")])
            session.commit()
        trace = {"arret_depart_id": "a", "arret_arrivee_id": "b", "geometrie": "[[0,0],[1,1]]", "longueur_km": 1.0, "sur_voie": False}
        trace_trajets.charger([trace], engine)
        assert trace_trajets.charger([trace], engine) == 1
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(TraceTrajet)) == 1
