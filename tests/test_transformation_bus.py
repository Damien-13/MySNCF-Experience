"""Vérifie la transformation des réseaux urbains (src/transformation/bus.py) sur une base SQLite temporaire, supprimée à la fin."""
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

import bus
import gtfs
import migration
from lib.db.connection import get_engine
from lib.db.models import Arret, Ligne, Lieu, Passage


@pytest.fixture
def db(monkeypatch):
    with tempfile.TemporaryDirectory() as folder:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{folder}/test.db")
        migration.migrate()
        with get_engine().begin() as conn:
            conn.execute(Lieu.__table__.insert(), [{"id": 1, "type": "gare", "source": "gares_voyageurs", "nom": "Nantes", "lat": 47.217, "lon": -1.542}])
        yield


def test_type_ligne():
    assert [bus.type_ligne(t) for t in ("3", "0", "1", "4", "11", "715", "900", "1200", None, "abc")] == \
        ["Bus", "Tramway", "Métro", "Bateau", "Trolleybus", "Bus", "Tramway", "Bateau", "Bus", "Bus"]


BRUT = {
    "routes": pd.DataFrame({"route_id": ["L1", "T1", "L1"], "route_short_name": ["1", "T1", "1"], "route_type": ["3", "0", "3"]}),     # L1 en double
    "trips": pd.DataFrame({"route_id": ["L1", "T1", "ZZ"], "service_id": ["S", "S", "S"], "trip_id": ["a", "b", "c"], "trip_headsign": ["Centre", "Gare", "?"]}),
    "stop_times": pd.DataFrame({"trip_id": ["a", "a", "a", "b", "b", "c"], "stop_sequence": ["1", "2", "2", "1", "2", "1"],      # rang 2 en double pour a
                                "stop_id": ["s1", "s2", "s3", "s1", "s2", "s1"], "arrival_time": ["08:00:00"] * 6, "departure_time": ["08:00:30"] * 6}),
    "stops": pd.DataFrame({"stop_id": ["s1", "s2", "s3"], "stop_name": ["Commerce", "Gare Nord", "Loin"],
                           "stop_lat": ["47.2132", "47.2181", "47.3"], "stop_lon": ["-1.5560", "-1.5430", "-1.5"]}),     # pas de location_type
    "calendar": pd.DataFrame({"service_id": ["S"], "monday": ["1"], "tuesday": ["0"], "wednesday": ["0"], "thursday": ["0"], "friday": ["0"],
                              "saturday": ["0"], "sunday": ["0"], "start_date": ["20261012"], "end_date": ["20261019"]}),
    "calendar_dates": pd.DataFrame(),
}


def test_nettoyer_tolere_les_fichiers_imparfaits():
    f = bus.nettoyer({k: v.copy() for k, v in BRUT.items()}, "nantes")
    assert sorted(f["lignes"]["id"]) == ["nantes:L1", "nantes:T1"]                        # ligne en double retirée
    assert dict(zip(f["lignes"]["id"], f["lignes"]["type_transport"])) == {"nantes:L1": "Bus", "nantes:T1": "Tramway"}
    assert list(f["circulations"]["id"]) == ["nantes:a", "nantes:b"]                      # circulation d'une ligne inconnue écartée
    assert len(f["passages"]) == 4                                                        # rang en double et circulation inconnue retirés
    assert len(f["calendrier"]) == 2                                                      # deux lundis : 12 et 19 octobre


def test_charger_cree_des_arrets_bus_sans_les_rattacher_aux_gares(db):
    f = bus.nettoyer({k: v.copy() for k, v in BRUT.items()}, "nantes")
    assert gtfs.charger(f, {"id": "nantes", "nom": "Naolib (Nantes)", "mode": "bus"}, "bus_nantes_naolib", type_lieu="arret_bus") == (2, 2, 2, 4)
    gtfs.charger(f, {"id": "nantes", "nom": "Naolib (Nantes)", "mode": "bus"}, "bus_nantes_naolib", type_lieu="arret_bus")      # relance
    with Session(get_engine()) as s:
        arrets = {a.nom: a for a in s.scalars(select(Arret))}
        nord = s.get(Lieu, arrets["Gare Nord"].lieu_id)
        assert nord.type == "arret_bus" and nord.id != 1                                   # son propre lieu, pas la gare de Nantes pourtant à 500 m
        assert nord.gare_proche_id == 1 and 0 < nord.distance_gare_km < 1
        assert s.scalar(select(func.count()).select_from(Lieu).where(Lieu.type == "arret_bus")) == 2
        assert s.scalar(select(func.count()).select_from(Passage)) == 4 and s.scalar(select(func.count()).select_from(Ligne)) == 2
