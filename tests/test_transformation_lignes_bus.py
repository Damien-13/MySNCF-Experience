"""Vérifie la transformation des lignes de bus (src/transformation/lignes_bus.py) et leur rapprochement avec les arrêts d'un car (lib/trace_bus.py),
sur une base SQLite temporaire, supprimée à la fin. La lecture du fichier OpenStreetMap n'est pas testée (5 Go) : on part de lignes déjà lues."""
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "migrations"))
sys.path.insert(0, str(ROOT / "src" / "transformation"))

from sqlalchemy import select
from sqlalchemy.orm import Session

import lignes_bus
import migration
from lib import trace_bus
from lib.db.connection import get_engine
from lib.db.models import LigneBus


@pytest.fixture
def db(monkeypatch):
    with tempfile.TemporaryDirectory() as folder:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{folder}/test.db")
        migration.migrate()
        trace_bus._chercher.cache_clear()
        yield


def _tags(**t):
    return {"ref": None, "name": None, "network": None, "operator": None, "from": None, "to": None, **t}


# Une route de 0,3° (environ 24 km) vers l'est, en deux tronçons bout à bout, plus une ligne trop courte et une ligne sans tracé.
ROUTE = [[(5.0, 44.0), (5.15, 44.0)], [(5.15, 44.0), (5.3, 44.0)]]
LIGNES = [
    {"id": 1, "tags": _tags(ref="400", name="Bus 400 : A => B", network="Zou !"), "troncons": ROUTE},
    {"id": 2, "tags": _tags(ref="9"), "troncons": [[(5.0, 44.0), (5.001, 44.0)]]},      # moins de 0,3 km : écartée
    {"id": 3, "tags": _tags(ref="10"), "troncons": []},                                  # aucun tronçon : écartée
]


def test_nettoyer_fusionne_les_troncons_et_ecarte_les_lignes_inutilisables():
    lignes = lignes_bus.nettoyer(LIGNES)
    assert [l["id"] for l in lignes] == [1]
    ligne = lignes[0]
    assert ligne["ref"] == "400" and ligne["reseau"] == "Zou !"
    assert len(json.loads(ligne["geometrie"])) == 1                   # les deux tronçons bout à bout forment une seule polyligne
    assert 20 < ligne["longueur_km"] < 25
    assert (ligne["lon_min"], ligne["lon_max"], ligne["lat_min"], ligne["lat_max"]) == (5.0, 5.3, 44.0, 44.0)


def test_charger_remplace_toutes_les_lignes(db):
    engine = get_engine()
    lignes = lignes_bus.nettoyer(LIGNES)
    assert lignes_bus.charger(lignes, engine) == 1
    assert lignes_bus.charger(lignes, engine) == 1                    # relançable : pas de doublon
    with Session(engine) as s:
        assert [l.id for l in s.scalars(select(LigneBus))] == [1]


def test_trace_car_suit_la_ligne_qui_dessert_les_arrets(db):
    engine = get_engine()
    lignes_bus.charger(lignes_bus.nettoyer(LIGNES), engine)
    points, sur_route = trace_bus.trace_car([(5.02, 44.001), (5.2, 44.001), (5.28, 43.999)], engine)
    assert sur_route
    assert points[0] == (5.02, 44.001) and points[-1] == (5.28, 43.999)   # le tracé part du premier arrêt et finit au dernier
    assert len(points) > 3                                                # il suit la route : plus de points que d'arrêts
    assert all(abs(lat - 44.0) < 0.01 for _, lat in points[1:-1])


def test_trace_car_sans_ligne_relie_les_arrets_en_ligne_droite(db):
    engine = get_engine()
    lignes_bus.charger(lignes_bus.nettoyer(LIGNES), engine)
    arrets = [(2.0, 48.0), (2.1, 48.0)]                               # loin de toute ligne
    assert trace_bus.trace_car(arrets, engine) == (arrets, False)
    assert trace_bus.trace_car([(5.1, 44.0)], engine) == ([(5.1, 44.0)], False)   # un seul arrêt : rien à tracer


def test_trace_car_ecarte_une_ligne_qui_ne_passe_pas_par_tous_les_arrets(db):
    engine = get_engine()
    lignes_bus.charger(lignes_bus.nettoyer(LIGNES), engine)
    arrets = [(5.02, 44.0), (5.2, 44.1), (5.28, 44.0)]                # le second arrêt est à plus de 10 km de la route
    assert trace_bus.trace_car(arrets, engine) == (arrets, False)
