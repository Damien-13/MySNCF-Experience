"""Vérifie le réseau routier : découpage des routes aux carrefours (src/transformation/routes.py) et trajet d'un car arrêt par arrêt (lib/reseau_routier.py),
sur une base SQLite temporaire, supprimée à la fin. La lecture du fichier OpenStreetMap n'est pas testée (5 Go) : on part de routes déjà lues."""
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "migrations"))
sys.path.insert(0, str(ROOT / "src" / "transformation"))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import migration
import routes
from lib import reseau_routier, trace_bus
from lib.db.connection import get_engine
from lib.db.models import TronconRoute
from lib.reseau_ferre import longueur_km

E_ = routes.ECHELLE


def _tableaux(chemins):
    """Tableaux compacts comme les lit routes._Routes : chemins = [(classe, sens, [(id, lon, lat), …]), …]."""
    ids, lons, lats, debuts, classes, sens = [], [], [], [0], [], []
    for classe, s, noeuds in chemins:
        for i, lon, lat in noeuds:
            ids.append(i); lons.append(round(lon * E_)); lats.append(round(lat * E_))
        debuts.append(len(ids)); classes.append(classe); sens.append(s)
    return ids, lons, lats, debuts, classes, sens


# Un carrefour (nœud 3) entre une route est-ouest (nœuds 1-2-3-4-5, à 44° de latitude) et une route qui part vers le nord (nœuds 3-6).
EST_OUEST = ("primary", 0, [(1, 5.00, 44.0), (2, 5.05, 44.0), (3, 5.10, 44.0), (4, 5.15, 44.0), (5, 5.20, 44.0)])
NORD = ("secondary", 0, [(3, 5.10, 44.0), (6, 5.10, 44.05)])
NORD_SENS_UNIQUE = ("secondary", 1, [(3, 5.10, 44.0), (6, 5.10, 44.05)])         # à sens unique vers le nord (utilisé pour tester le découpage)


@pytest.fixture
def db(monkeypatch):
    with tempfile.TemporaryDirectory() as folder:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{folder}/test.db")
        migration.migrate()
        trace_bus._chercher.cache_clear()
        yield


def test_decouper_coupe_les_routes_aux_carrefours():
    troncons = routes.decouper(*_tableaux([EST_OUEST, NORD]))
    assert sorted((t["classe"], len(json.loads(t["geometrie"]))) for t in troncons) == [("primary", 3), ("primary", 3), ("secondary", 2)]
    assert [t["sens"] for t in routes.decouper(*_tableaux([EST_OUEST, NORD_SENS_UNIQUE])) if t["classe"] == "secondary"] == [1]
    assert all(t["longueur_m"] > 0 for t in troncons)
    assert {t["tuile"] for t in troncons if t["classe"] == "secondary"} == {reseau_routier.tuile(5.1, 44.0)}


def test_decouper_sans_route():
    assert routes.decouper([], [], [], [0], [], []) == []


def test_sens_unique_et_acces():
    assert routes.sens_unique({"oneway": "yes"}) == 1
    assert routes.sens_unique({"oneway": "-1"}) == -1
    assert routes.sens_unique({"junction": "roundabout"}) == 1
    assert routes.sens_unique({"highway": "motorway"}) == 1
    assert routes.sens_unique({"highway": "motorway", "oneway": "no"}) == 0
    assert routes.sens_unique({"oneway": "yes", "oneway:bus": "no"}) == 0           # voie à contresens réservée aux bus
    assert not routes.autocar_admis({"highway": "tertiary", "access": "private"})
    assert routes.autocar_admis({"highway": "tertiary", "access": "private", "bus": "yes"})
    assert not routes.autocar_admis({"highway": "tertiary", "bus": "no"})
    assert routes.autocar_admis({"highway": "tertiary"})


def test_charger_remplace_tout_le_reseau(db):
    engine = get_engine()
    troncons = routes.decouper(*_tableaux([EST_OUEST, NORD]))
    assert routes.charger(troncons, engine) == 3
    assert routes.charger(troncons, engine) == 3                       # relançable : pas de doublon
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(TronconRoute)) == 3


def test_chemin_par_arrets_suit_les_routes(db):
    engine = get_engine()
    routes.charger(routes.decouper(*_tableaux([EST_OUEST, NORD])), engine)
    points, complet = reseau_routier.chemin_par_arrets([(5.01, 44.001), (5.10, 44.04), (5.19, 43.999)], engine)
    assert complet
    assert points[0] == (5.01, 44.001) and points[-1] == (5.19, 43.999)      # de l'arrêt de départ à l'arrêt d'arrivée
    lons = [lon for lon, _ in points]
    assert max(lat for _, lat in points) > 44.04 and min(lons) <= 5.01 + 0.01 and max(lons) >= 5.19 - 0.01   # il monte au nord par la route, puis revient (demi-tour)


def test_sens_unique_respecte(db):
    engine = get_engine()
    # un rond-point à sens unique 3 → 6 → 7 → 3, relié à la route est-ouest : de 6 à 7 le chemin est direct, de 7 à 6 il faut faire le tour
    rond_point = ("secondary", 1, [(3, 5.10, 44.0), (6, 5.12, 44.02), (7, 5.08, 44.02), (3, 5.10, 44.0)])
    routes.charger(routes.decouper(*_tableaux([EST_OUEST, rond_point])), engine)
    direct, complet = reseau_routier.chemin_par_arrets([(5.12, 44.02), (5.08, 44.02)], engine)
    detour, complet_detour = reseau_routier.chemin_par_arrets([(5.08, 44.02), (5.12, 44.02)], engine)
    assert complet and complet_detour
    assert longueur_km(detour) > 1.3 * longueur_km(direct)


def test_arret_loin_de_toute_route(db):
    engine = get_engine()
    routes.charger(routes.decouper(*_tableaux([EST_OUEST, NORD])), engine)
    assert reseau_routier.chemin_par_arrets([(5.0, 44.0), (5.1, 44.2)], engine) is None      # le second arrêt est à 20 km d'une route
    assert reseau_routier.chemin_par_arrets([(2.0, 48.0), (2.1, 48.0)], engine) is None      # aucune route dans la zone


def test_trace_car_utilise_les_routes_sans_ligne_osm(db):
    engine = get_engine()
    routes.charger(routes.decouper(*_tableaux([EST_OUEST, NORD])), engine)
    points, sur_route = trace_bus.trace_car([(5.01, 44.001), (5.19, 43.999)], engine)      # table ligne_bus vide : repli sur le routage
    assert sur_route and len(points) > 2
