"""Vérifie le GTFS générique (gtfs.py) et les réseaux Transilien et trains européens, sur une base SQLite temporaire supprimée à la fin."""
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

from sqlalchemy import select
from sqlalchemy.orm import Session

import gtfs
import migration
import trains_europeens
import transilien
from lib.db.connection import get_engine
from lib.db.models import Arret, Gare, Ligne, Lieu


@pytest.fixture
def db(monkeypatch):
    with tempfile.TemporaryDirectory() as folder:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{folder}/test.db")
        migration.migrate()
        with get_engine().begin() as conn:
            conn.execute(Lieu.__table__.insert(), [
                {"id": 1, "type": "gare", "source": "gares_voyageurs", "nom": "Magenta", "lat": 48.8799, "lon": 2.3584},
                {"id": 2, "type": "gare", "source": "gares_voyageurs", "nom": "Paris Gare du Nord", "lat": 48.8802, "lon": 2.3552}])
            conn.execute(Gare.__table__.insert(), [{"lieu_id": 1, "code_uic": "87271296"}, {"lieu_id": 2, "code_uic": "87271007"}])
        yield


def test_mots():
    assert gtfs.mots("Paris Gare du Nord") == {"nord"} and gtfs.mots("Gare de l'Est") == {"est"}
    assert gtfs.mots("Aéroport CDG 1 (Terminal 3)") == {"cdg", "terminal"}


def test_jours_de_circulation():
    brut = {
        "calendar": pd.DataFrame({"service_id": ["S1"], "monday": ["1"], "tuesday": ["0"], "wednesday": ["0"], "thursday": ["0"], "friday": ["1"],
                                  "saturday": ["0"], "sunday": ["0"], "start_date": ["20261005"], "end_date": ["20261016"]}),
        "calendar_dates": pd.DataFrame({"service_id": ["S1", "S1", "S2"], "date": ["20261009", "20261010", "20261020"], "exception_type": ["2", "1", "1"]}),
    }
    out = gtfs.jours_de_circulation(brut)
    s1 = sorted(out[out["service_id"] == "S1"]["date"].dt.date)
    # lundis et vendredis du 5 au 16 oct. = 5, 9, 12, 16 ; le 9 est retiré, le samedi 10 est ajouté
    assert s1 == [date(2026, 10, 5), date(2026, 10, 10), date(2026, 10, 12), date(2026, 10, 16)]
    assert list(out[out["service_id"] == "S2"]["date"].dt.date) == [date(2026, 10, 20)]


def test_garder_lignes():
    brut = {"routes": pd.DataFrame({"route_id": ["A", "B"]}), "trips": pd.DataFrame({"route_id": ["A", "B"], "trip_id": ["1", "2"]}),
            "stop_times": pd.DataFrame({"trip_id": ["1", "2"], "stop_id": ["x", "y"]})}
    out = gtfs.garder_lignes(brut, brut["routes"]["route_id"] == "A")
    assert list(out["trips"]["trip_id"]) == ["1"] and list(out["stop_times"]["stop_id"]) == ["x"]


def test_rattacher_par_position_prefere_le_nom_compatible():
    gares = pd.DataFrame({"id": [1, 2], "nom": ["Magenta", "Paris Gare du Nord"], "lat": [48.8799, 48.8802], "lon": [2.3584, 2.3552]})
    # l'arrêt est plus proche de Magenta (~65 m) que de la gare du Nord (~170 m) : le nom tranche
    arrets = pd.DataFrame({"nom": ["Paris Gare du Nord", "Arrêt sans rapport", "Arrêt sans rapport"],
                           "lat": [48.87995, 48.87995, 48.9], "lon": [2.3575, 2.3575, 2.5]})
    assert gtfs.rattacher_par_position(arrets, gares, 300) == [2, None, None]    # sans nom compatible : ni l'un ni l'autre (>50 m), ni rien à 300 m
    proche = pd.DataFrame({"nom": ["Autre nom"], "lat": [48.87991], "lon": [2.35841]})
    assert gtfs.rattacher_par_position(proche, gares, 300) == [1]               # à moins de 50 m : accepté malgré le nom


TRANSILIEN = {
    "agency": pd.DataFrame({"agency_id": ["71", "1046", "93"], "agency_name": ["RER", "Transilien", "TER"]}),
    "routes": pd.DataFrame({"route_id": ["RA", "TH", "TB", "TER1", "RR"], "agency_id": ["71", "1046", "71", "93", "71"],
                            "route_short_name": ["A", "H", "B", "TER", "A"], "route_long_name": ["A", "H", "Remplacement RER B", "TER Normandie", "Remplacement RER A"],
                            "route_type": ["2", "2", "3", "2", "3"], "route_color": ["E2231A", None, None, None, None]}),
    "trips": pd.DataFrame({"route_id": ["RA", "TH", "TER1"], "service_id": ["S1", "S1", "S1"], "trip_id": ["1", "2", "3"],
                           "trip_headsign": ["Boissy", "Pontoise", "Rouen"], "trip_short_name": ["ABCD", "3376", "9999"], "block_id": [None, None, None]}),
    "stop_times": pd.DataFrame({"trip_id": ["1", "1", "2", "3"], "stop_sequence": ["0", "1", "0", "0"], "stop_id": ["a", "b", "a", "a"],
                                "arrival_time": ["08:00:00"] * 4, "departure_time": ["08:01:00"] * 4}),
    "stops": pd.DataFrame({"stop_id": ["a", "b"], "stop_name": ["Paris Gare du Nord", "Chelles"], "stop_lat": ["48.88", "48.88"],
                           "stop_lon": ["2.355", "2.60"], "location_type": ["0", "0"]}),
    "calendar": pd.DataFrame({"service_id": ["S1"], "monday": ["1"], "tuesday": ["1"], "wednesday": ["1"], "thursday": ["1"], "friday": ["1"],
                              "saturday": ["0"], "sunday": ["0"], "start_date": ["20261012"], "end_date": ["20261013"]}),
    "calendar_dates": pd.DataFrame(),
}


def test_transilien_ecarte_les_ter_et_type_les_lignes():
    f = transilien.nettoyer({k: v.copy() for k, v in TRANSILIEN.items()})
    lignes = f["lignes"].set_index("id")
    assert set(lignes.index) == {"transilien:RA", "transilien:TH", "transilien:TB", "transilien:RR"}       # ligne TER écartée
    assert lignes.loc["transilien:RA", ["nom", "type_transport"]].tolist() == ["RER A", "RER"]
    assert lignes.loc["transilien:TH", ["nom", "type_transport"]].tolist() == ["Transilien H", "Transilien"]
    assert lignes.loc["transilien:TB", ["nom", "type_transport"]].tolist() == ["Remplacement RER B", "Car de remplacement"]
    assert list(f["circulations"]["numero"]) == ["ABCD", "3376"] and "transilien:3" not in set(f["circulations"]["id"])
    assert len(f["calendrier"]) == 2 and len(f["passages"]) == 3


def test_transilien_charge_avec_rattachement_par_position(db):
    f = transilien.nettoyer({k: v.copy() for k, v in TRANSILIEN.items()})
    gtfs.charger(f, transilien.RESEAU, "transilien", rayon_gare_m=300)
    with Session(get_engine()) as s:
        arret = {a.nom: a for a in s.scalars(select(Arret))}
        assert arret["Paris Gare du Nord"].lieu_id == 2                          # la gare du bon nom, pas Magenta
        assert s.get(Lieu, arret["Chelles"].lieu_id).type == "arret_train"       # aucune gare à 300 m : son propre lieu
        assert len(list(s.scalars(select(Ligne)))) == 4


def test_eurostar_uic_a_7_chiffres(db):
    stops = pd.DataFrame({"stop_id": ["paris_nord", "paris_nord_2", "londres"], "stop_code": ["8727100", "8727100", "7015400"]})
    assert trains_europeens.codes_uic(stops, ["87271007", "87271296"]) == {"paris_nord": "87271007", "paris_nord_2": "87271007"}
