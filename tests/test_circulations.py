"""Vérifie les trains en circulation sur tout le réseau (lib/circulations.py) sur une base SQLite temporaire, supprimée à la fin."""
import json
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "migrations"))

from shapely.geometry import LineString, Point
from sqlalchemy.orm import Session

import migration
from lib import circulations
from lib.db.connection import get_engine
from lib.db.models import Arret, Calendrier, Circulation, Ligne, Passage, Reseau, TraceTrajet

JOUR = date(2026, 10, 12)
HIER = date(2026, 10, 11)
TRACE = json.dumps([[2.0, 48.0], [2.1, 48.0], [2.2, 48.0]])            # [lon, lat] : trace_trajet stocke les points dans cet ordre


@pytest.fixture
def engine(monkeypatch):
    circulations._cache.clear()
    with tempfile.TemporaryDirectory() as dossier:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{dossier}/test.db")
        migration.migrate()
        with Session(get_engine()) as s:
            s.add_all([Reseau(id="sncf", nom="SNCF", mode="train"), Reseau(id="ville", nom="Bus", mode="bus")])
            s.add_all([Arret(id="a", reseau_id="sncf", nom="Gare A"), Arret(id="b", reseau_id="sncf", nom="Gare B")])
            s.add_all([Ligne(id="l1", reseau_id="sncf", type_transport="TGV INOUI"), Ligne(id="l2", reseau_id="sncf", type_transport="Car TER"),
                       Ligne(id="l3", reseau_id="ville", type_transport="Bus")])
            s.add_all([Circulation(id="c1", ligne_id="l1", service_id="s_jour", numero="6101"),
                       Circulation(id="c_nuit", ligne_id="l1", service_id="s_hier", numero="7001"),
                       Circulation(id="c_car", ligne_id="l2", service_id="s_jour", numero="9"),
                       Circulation(id="c_bus", ligne_id="l3", service_id="s_jour", numero="1"),
                       Circulation(id="c_autre", ligne_id="l1", service_id="s_absent", numero="1")])
            s.add_all([Calendrier(service_id="s_jour", date=JOUR), Calendrier(service_id="s_hier", date=HIER)])
            for circ, depart, arrivee in (("c1", 8 * 3600, 9 * 3600), ("c_nuit", 23 * 3600 + 30 * 60, 25 * 3600), ("c_car", 8 * 3600, 9 * 3600),
                                          ("c_bus", 8 * 3600, 9 * 3600), ("c_autre", 8 * 3600, 9 * 3600)):
                s.add_all([Passage(circulation_id=circ, ordre=0, arret_id="a", heure_arrivee=depart, heure_depart=depart),
                           Passage(circulation_id=circ, ordre=1, arret_id="b", heure_arrivee=arrivee, heure_depart=arrivee)])
            s.add(TraceTrajet(arret_depart_id="a", arret_arrivee_id="b", geometrie=TRACE, longueur_km=15.0, sur_voie=True))
            s.commit()
        yield get_engine()


def test_trains_en_cours_a_une_heure_donnee(engine):
    trains = circulations.en_cours(datetime(2026, 10, 12, 8, 30), engine)
    assert [t["id"] for t in trains] == ["c1"]                           # ni le car, ni le bus, ni le service qui ne roule pas ce jour-là
    t = trains[0]
    assert t["libelle"] == "TGV INOUI 6101" and t["style"]["cle"] == "inoui" and (t["de"], t["vers"]) == ("Gare A", "Gare B")
    assert t["sur_voie"] is True
    assert t["sprite"] == "inoui" and t["longueur_m"] == 200 and t["rapport"] > 10             # l'image du train et sa taille réelle, pour le navigateur
    assert t["points"][0] == [48.0, 2.0] and t["points"][-1] == [48.0, 2.2]      # converti en [lat, lon] pour la carte
    assert t["t1"] - t["t0"] == 3600 and datetime.fromtimestamp(t["t0"]) == datetime(2026, 10, 12, 8, 0)


def test_fenetre_avant_le_depart_et_apres_l_arrivee(engine):
    assert [t["id"] for t in circulations.en_cours(datetime(2026, 10, 12, 7, 50), engine)] == ["c1"]       # part dans 10 min : dans la fenêtre de 15 min
    assert circulations.en_cours(datetime(2026, 10, 12, 7, 0), engine) == []
    assert circulations.en_cours(datetime(2026, 10, 12, 9, 30), engine) == []


def test_train_de_nuit_apres_minuit_appartient_au_service_de_la_veille(engine):
    trains = circulations.en_cours(datetime(2026, 10, 12, 0, 30), engine)       # 25 h du service du 11 = 1 h du matin le 12
    assert [t["id"] for t in trains] == ["c_nuit"]
    assert datetime.fromtimestamp(trains[0]["t1"]) == datetime(2026, 10, 12, 1, 0)


def test_sans_trace_en_base_rien_n_est_affiche(engine):
    from sqlalchemy import delete
    with Session(engine) as s:
        s.execute(delete(TraceTrajet))
        s.commit()
    circulations._cache.clear()
    assert circulations.en_cours(datetime(2026, 10, 12, 8, 30), engine) == []


def test_simplification_garde_la_forme_des_courbes():
    # Un quart de cercle de 6 km de rayon décrit par 200 points : 12 points pris au hasard le couperaient, ici l'écart reste sous la tolérance.
    import math
    arc = [[2.0 + 0.08 * math.sin(a / 200 * math.pi / 2), 48.0 + 0.054 * (1 - math.cos(a / 200 * math.pi / 2))] for a in range(201)]
    simple = circulations._simplifier(arc)
    assert 12 < len(simple) < len(arc) and simple[0] == arc[0] and simple[-1] == arc[-1]
    ecart = max(LineString(simple).distance(Point(p)) for p in arc)
    assert ecart <= circulations.TOLERANCE_DEG + 1e-9
    assert circulations._simplifier([[0, 0], [1, 1]]) == [[0, 0], [1, 1]]
