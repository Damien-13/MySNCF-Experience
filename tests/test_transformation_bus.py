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


def test_lire_passages_en_plusieurs_paquets(tmp_path, monkeypatch):
    monkeypatch.setattr(gtfs, "PAQUET_LECTURE", 2)                                    # force plusieurs paquets, aux catégories différentes
    fichier = tmp_path / "stop_times.txt"
    pd.DataFrame({"trip_id": ["a", "a", "b", "b", "c"], "arrival_time": ["08:00:00", "08:10:00", "25:00:00", "25:05:00", "09:00:00"],
                  "departure_time": ["08:00:30", "08:10:00", "25:00:00", "25:05:30", "09:00:00"], "stop_id": ["s1", "s2", "s3", "s1", "s2"],
                  "stop_sequence": ["1", "2", "1", "2", "1"], "colonne_inutile": ["x"] * 5}).to_csv(fichier, index=False)
    tout = gtfs.lire_passages(fichier)
    assert list(tout["trip_id"]) == ["a", "a", "b", "b", "c"] and list(tout["stop_id"]) == ["s1", "s2", "s3", "s1", "s2"]
    assert list(tout["heure_arrivee"]) == [28800, 29400, 90000, 90300, 32400] and "colonne_inutile" not in tout
    assert list(gtfs.lire_passages(fichier, {"b"})["trip_id"]) == ["b", "b"]          # seules les circulations demandées


def test_format_compact_et_texte_donnent_les_memes_passages(tmp_path):
    dossier = tmp_path / "gtfs"
    dossier.mkdir()
    for nom in ("routes", "trips", "stops"):
        BRUT[nom].to_csv(dossier / f"{nom}.txt", index=False)
    BRUT["stop_times"].to_csv(dossier / "stop_times.txt", index=False)
    BRUT["calendar"].to_csv(dossier / "calendar.txt", index=False)
    compact = bus.nettoyer(gtfs.lire(dossier), "nantes")
    texte = bus.nettoyer({k: v.copy() for k, v in BRUT.items()}, "nantes")
    cols = ["circulation_id", "ordre", "arret_id", "heure_arrivee", "heure_depart"]
    a = compact["passages"][cols].astype({"circulation_id": str, "arret_id": str}).reset_index(drop=True)
    b = texte["passages"][cols].reset_index(drop=True).astype({"ordre": a["ordre"].dtype, "heure_arrivee": float, "heure_depart": float})
    pd.testing.assert_frame_equal(a.astype({"heure_arrivee": float, "heure_depart": float}), b, check_dtype=False)


def test_idfm_ecarte_les_trains(tmp_path):
    dossier = tmp_path / "gtfs"
    dossier.mkdir()
    pd.DataFrame({"route_id": ["M1", "RERA", "B1"], "route_type": ["1", "2", "3"]}).to_csv(dossier / "routes.txt", index=False)
    pd.DataFrame({"route_id": ["M1", "RERA", "B1"], "service_id": ["S"] * 3, "trip_id": ["m", "r", "b"]}).to_csv(dossier / "trips.txt", index=False)
    pd.DataFrame({"stop_id": ["s"], "stop_lat": ["48.8"], "stop_lon": ["2.3"]}).to_csv(dossier / "stops.txt", index=False)
    pd.DataFrame({"trip_id": ["m", "r", "b"], "arrival_time": ["08:00:00"] * 3, "departure_time": ["08:00:00"] * 3, "stop_id": ["s"] * 3,
                  "stop_sequence": ["1"] * 3}).to_csv(dossier / "stop_times.txt", index=False)
    brut = gtfs.lire(dossier, lignes=bus.LIGNES_GARDEES["idfm"])
    assert sorted(brut["routes"]["route_id"]) == ["B1", "M1"] and sorted(brut["trips"]["trip_id"]) == ["b", "m"]
    assert sorted(brut["stop_times"]["trip_id"]) == ["b", "m"]                         # les passages du RER ne sont même pas lus
