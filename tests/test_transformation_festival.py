"""Vérifie la transformation des festivals (src/transformation/festival.py) sur une base SQLite temporaire, supprimée à la fin."""
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

import festival
import migration
from lib.db.connection import get_engine
from lib.db.models import Evenement, EvenementPeriode, Lieu

ANNEES = (2026,)


@pytest.fixture
def db(monkeypatch):
    with tempfile.TemporaryDirectory() as folder:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{folder}/test.db")
        migration.migrate()
        yield


BRUT = pd.DataFrame({
    "Nom du festival": ["Celte", "Celte bis", "Corse", "Sans date", "Octobre rock", "Ailleurs"],
    "Commune principale de déroulement": ["Saugues", "Saugues", "Ajaccio", "Privas", "Lyon", "Paris"],
    "Code postal (de la commune principale de déroulement)": ["43170", "43170", "20000", "07000", "69001", "75001"],
    "Adresse postale": [None] * 6,
    "Période principale de déroulement du festival": ["Saison (21 juin - 5 septembre)", "Saison (21 juin - 5 septembre)",
                                                      "Saison (21 juin - 5 septembre)", "Variable selon les années", "Ocotbre, Novembre", None],
    "Identifiant": ["F1", "F1", "F2", "F3", "F4", "F5"],
    "Géocodage xy": ["44.98, 3.54", "44.98, 3.54", "41.9, 8.7", "44.7, 4.6", "45.76, 4.83", None],
})


def test_fenetres():
    assert festival.fenetres("Avant-saison (1er janvier - 20 juin)") == [((1, 1), (6, 20))]
    assert festival.fenetres("après-saison (6 septembre - 31 décembre)") == [((9, 6), (12, 31))]
    assert festival.fenetres("Ocotbre, Novembre") == [((10, 1), (10, 31)), ((11, 1), (11, 30))]
    assert festival.fenetres("Variable selon les années") == [] and festival.fenetres(None) == []


def test_periodes_une_par_annee():
    p = festival.periodes("Février", (2026, 2027))
    assert list(p["date_debut"]) == [date(2026, 2, 1), date(2027, 2, 1)] and list(p["date_fin"]) == [date(2026, 2, 28), date(2027, 2, 28)]


def test_nettoyer():
    ev, plages = festival.nettoyer(BRUT, ANNEES)
    assert list(ev["nom"]) == ["Celte", "Octobre rock"]      # doublon, Corse, période variable, sans position écartés
    assert set(ev["categorie"]) == {"Festival"} and list(ev["departement"]) == ["43", "69"]
    assert list(plages["evenement"]) == [0, 1, 1]            # Celte : saison ; Octobre rock : octobre et novembre


def test_charger_et_relancer_sans_doublon(db):
    with get_engine().begin() as conn:
        conn.execute(Lieu.__table__.insert(), [{"id": 1, "type": "gare", "source": "gares_voyageurs", "nom": "Saugues", "lat": 44.96, "lon": 3.55}])
    ev, plages = festival.nettoyer(BRUT, ANNEES)
    ev = festival.rattacher_aux_gares(ev, festival.lire_gares())
    assert festival.evenement.charger(ev, plages, festival.SOURCE) == (2, 3) and festival.evenement.charger(ev, plages, festival.SOURCE) == (2, 3)
    with Session(get_engine()) as s:
        assert s.scalar(select(func.count()).select_from(Evenement).where(Evenement.source == "festivals")) == 2
        assert s.scalar(select(func.count()).select_from(EvenementPeriode)) == 3
        assert s.scalar(select(Lieu.gare_proche_id).where(Lieu.nom == "Celte")) == 1
