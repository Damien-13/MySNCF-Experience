"""Vérifie la transformation du tracé ferroviaire (src/transformation/voies.py) sur une base SQLite temporaire, supprimée à la fin."""
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
import voies
from lib.db.connection import get_engine
from lib.db.models import TronconVoie


@pytest.fixture
def db(monkeypatch):
    with tempfile.TemporaryDirectory() as folder:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{folder}/test.db")
        migration.migrate()
        yield


def _entite(parties, **attributs):
    return {"attributs": attributs, "parties": parties}


DROITE = [(2.0, 48.0), (2.001, 48.0), (2.002, 48.0), (2.1, 48.0)]   # points alignés : simplifiés en deux

VOIES = [
    _entite([DROITE], code_ligne="100000", type_voie="VPL", nom_voie="V1"),
    _entite([DROITE], code_ligne="100000", type_voie="VPA", nom_voie=""),
    _entite([DROITE], code_ligne="100000", type_voie="VS", nom_voie="garage"),      # voie de service : écartée
    _entite([[(2.0, 48.0)]], code_ligne="200000", type_voie="VPL", nom_voie="V1"),   # un seul point : écartée
]
LIGNES = [
    _entite([DROITE], code_ligne="100000", mnemo="EXPLOITE"),        # déjà couverte par une voie
    _entite([DROITE], code_ligne="300000", mnemo="EXPLOITE"),        # manque dans les voies : ajoutée
    _entite([DROITE], code_ligne="400000", mnemo="FERME"),           # fermée : écartée
    _entite([DROITE, [(3.0, 47.0), (3.1, 47.1)]], code_ligne="500000", mnemo="EXPLOITE"),   # deux parties
]


def test_nettoyer_voies_ecarte_service_et_geometries_trop_courtes():
    resultat = voies.nettoyer_voies(VOIES)
    assert [(t["code_ligne"], t["type_voie"], t["nom_voie"]) for t in resultat] == [("100000", "VPL", "V1"), ("100000", "VPA", None)]
    assert all(t["source"] == "voies" for t in resultat)


def test_geometrie_simplifiee_arrondie_et_longueur():
    t = voies.nettoyer_voies(VOIES)[0]
    assert json.loads(t["geometrie"]) == [[2.0, 48.0], [2.1, 48.0]]
    assert t["longueur_km"] == pytest.approx(7.43, abs=0.05)         # 0,1° de longitude à 48° de latitude


def test_lignes_completent_seulement_les_codes_sans_voie():
    resultat = voies.completer_avec_lignes(LIGNES, voies.nettoyer_voies(VOIES))
    assert sorted(t["code_ligne"] for t in resultat) == ["300000", "500000", "500000"]      # 400000 fermée, 100000 déjà couverte
    assert all(t["source"] == "lignes" and t["type_voie"] is None for t in resultat)


def test_charger_remplace_tout_le_trace(db):
    voies.charger(voies.nettoyer_voies(VOIES))
    assert voies.charger(voies.completer_avec_lignes(LIGNES, [])) == 4            # sans voies : 100000, 300000 et 500000 (2 parties)
    with Session(get_engine()) as session:
        assert session.scalar(select(func.count()).select_from(TronconVoie)) == 4
        assert session.scalar(select(func.count()).where(TronconVoie.source == "voies")) == 0
