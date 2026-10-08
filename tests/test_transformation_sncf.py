"""Vérifie la transformation du GTFS SNCF (src/transformation/gtfs.py, sncf.py) sur une base SQLite temporaire, supprimée à la fin."""
import sys
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "migrations"))
sys.path.insert(0, str(ROOT / "src" / "transformation"))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import gtfs
import migration
import sncf
from lib.db.connection import get_engine
from lib.db.models import Arret, Calendrier, Circulation, Ligne, Lieu, Passage, Reseau


@pytest.fixture
def db(monkeypatch):
    with tempfile.TemporaryDirectory() as folder:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{folder}/test.db")
        migration.migrate()
        with get_engine().begin() as conn:
            conn.execute(Lieu.__table__.insert(), [{"id": 1, "type": "gare", "source": "gares_voyageurs", "nom": "Blois", "lat": 47.58, "lon": 1.32},
                                                   {"id": 2, "type": "gare", "source": "gares_voyageurs", "nom": "Orléans", "lat": 47.91, "lon": 1.90}])
            conn.execute(sa_insert_gare(), [{"lieu_id": 1, "code_uic": "87574004"}, {"lieu_id": 2, "code_uic": "87543009"}])
        yield


def sa_insert_gare():
    from lib.db.models import Gare
    return Gare.__table__.insert()


def stops(*lignes):
    return pd.DataFrame(lignes, columns=["stop_id", "stop_name", "stop_lat", "stop_lon", "location_type"])


BRUT = {
    "routes": pd.DataFrame({"route_id": ["R1", "R2"], "route_short_name": ["P1", "C1"], "route_long_name": ["Orléans - Blois", None],
                            "route_color": ["0749FF", None]}),
    "trips": pd.DataFrame({"route_id": ["R1", "R1", "R2"], "service_id": ["S1", "S1", "S2"], "trip_id": ["T1", "T2", "T3"],
                           "trip_headsign": ["Blois", "Orléans", "Madrid"], "block_id": ["8601", "8602", "9700"]}),
    "stop_times": pd.DataFrame({
        "trip_id": ["T1", "T1", "T2", "T2", "T3", "T3"], "stop_sequence": ["0", "1", "0", "1", "0", "1"],
        "stop_id": ["StopPoint:OCETrain TER-87543009", "StopPoint:OCETrain TER-87574004", "StopPoint:OCETrain TER-87574004",
                    "StopPoint:OCETrain TER-87543009", "StopPoint:OCECar TER-87999001", "StopPoint:OCETGV INOUI-71718010"],
        "arrival_time": ["07:00:00", "07:40:00", "23:50:00", "25:10:00", "08:00:00", "09:30:00"],
        "departure_time": ["07:02:00", "07:41:00", "23:52:00", "25:10:00", "08:01:00", "09:31:00"]}),
    "stops": stops(("StopArea:OCE87574004", "BLOIS", "47.58", "1.32", "1"),
                   ("StopPoint:OCETrain TER-87574004", "Blois", "47.58", "1.32", "0"),
                   ("StopPoint:OCETrain TER-87543009", "Orléans", "47.91", "1.90", "0"),
                   ("StopPoint:OCECar TER-87999001", "Cravant Mairie", "47.80", "1.60", "0"),
                   ("StopPoint:OCETGV INOUI-71718010", "Barcelone-Sants", "41.38", "2.14", "0"),
                   ("StopPoint:OCETrain TER-87000000", "Arrêt jamais desservi", "47.0", "1.0", "0")),
    "calendar_dates": pd.DataFrame({"service_id": ["S1", "S1", "S2", "S2"], "date": ["20261012", "20261013", "20261012", "20261013"],
                                    "exception_type": ["1", "1", "1", "2"]}),
}


def test_en_secondes():
    out = gtfs.en_secondes(pd.Series(["07:02:00", "25:10:00", None, "abc", "00:00:00"]))
    assert out[0] == 25320 and out[1] == 90600 and out[4] == 0 and out[2] != out[2] and out[3] != out[3]


def test_uic_et_libelle():
    uic, libelle = sncf.uic_et_libelle(pd.Series(["StopPoint:OCECar TER-87999001", "StopArea:OCE87574004"]))
    assert uic["StopPoint:OCECar TER-87999001"] == "87999001" and libelle["StopPoint:OCECar TER-87999001"] == "Car TER"
    assert pd.isna(uic["StopArea:OCE87574004"])


def test_normaliser():
    f = sncf.nettoyer(BRUT)
    assert list(f["lignes"]["id"]) == ["sncf:R1", "sncf:R2"]
    assert list(f["lignes"]["type_transport"]) == ["Train TER", "Car TER"]      # type de la ligne = libellé de ses arrêts
    assert list(f["lignes"]["nom"]) == ["Orléans - Blois", "C1"] and list(f["lignes"]["couleur"][:1]) == ["#0749FF"]
    assert f["circulations"].loc[0, "numero"] == "8601" and f["circulations"].loc[0, "service_id"] == "sncf:S1"
    assert len(f["calendrier"]) == 3 and date(2026, 10, 13) not in set(f["calendrier"].query("service_id == 'sncf:S2'")["date"])  # jour retiré (type 2)
    assert 90600 in set(f["passages"]["heure_arrivee"])                          # 25:10 → après minuit
    assert "sncf:StopPoint:OCETrain TER-87000000" not in set(f["arrets"]["id"])  # arrêt jamais desservi écarté
    assert "StopArea" not in " ".join(f["arrets"]["id"])                         # zones d'arrêt écartées


def test_charger_rattache_aux_gares_et_cree_les_autres_arrets(db):
    f = sncf.nettoyer(BRUT)
    assert gtfs.charger(f, sncf.RESEAU, sncf.SOURCE) == (2, 3, 4, 6)
    with Session(get_engine()) as s:
        arret = {a.id: a for a in s.scalars(select(Arret))}
        assert arret["sncf:StopPoint:OCETrain TER-87574004"].lieu_id == 1          # gare connue → son lieu
        car = s.get(Lieu, arret["sncf:StopPoint:OCECar TER-87999001"].lieu_id)
        assert car.type == "arret_bus" and car.gare_proche_id in (1, 2) and car.distance_gare_km is not None
        etranger = s.get(Lieu, arret["sncf:StopPoint:OCETGV INOUI-71718010"].lieu_id)
        assert etranger.type == "arret_train" and etranger.gare_proche_id is None   # Barcelone : pas de gare « proche »
        assert s.scalar(select(Passage.heure_arrivee).where(Passage.circulation_id == "sncf:T2", Passage.ordre == 1)) == 90600


def test_relance_sans_doublon_et_sans_toucher_aux_autres_donnees(db):
    f = sncf.nettoyer(BRUT)
    gtfs.charger(f, sncf.RESEAU, sncf.SOURCE)
    gtfs.charger(f, sncf.RESEAU, sncf.SOURCE)
    with Session(get_engine()) as s:
        compte = lambda m: s.scalar(select(func.count()).select_from(m))
        assert (compte(Reseau), compte(Ligne), compte(Circulation), compte(Calendrier), compte(Arret), compte(Passage)) == (1, 2, 3, 3, 4, 6)
        assert s.scalar(select(func.count()).select_from(Lieu).where(Lieu.type == "gare")) == 2
        assert s.scalar(select(func.count()).select_from(Lieu)) == 4               # 2 gares + 1 car + 1 arrêt étranger : pas de lieux en double
