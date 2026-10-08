"""Vérifie la transformation des événements (src/transformation/evenement.py) sur une base SQLite temporaire, supprimée à la fin."""
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

import evenement
import migration
from lib.db.connection import get_engine
from lib.db.models import Evenement, EvenementLieu, EvenementPeriode, Lieu

CORE = "https://www.datatourisme.fr/ontology/core#"


@pytest.fixture
def db(monkeypatch):
    with tempfile.TemporaryDirectory() as folder:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{folder}/test.db")
        migration.migrate()
        yield


BRUT = pd.DataFrame({
    "Nom_du_POI": ["Hellfest", "Hellfest", "Fête corse", "Marché sans date", "Fête de l'an 2926", "Concert"],
    "Categories_de_POI": [CORE + "EntertainmentAndEvent|" + CORE + "Festival|" + CORE + "MusicEvent", "x", CORE + "Market",
                          CORE + "Market", CORE + "SocialEvent", CORE + "CulturalEvent|" + CORE + "Concert"],
    "Latitude": ["47.09", "47.09", "42.0", "45.0", "44.0", "45.76"],
    "Longitude": ["-1.28", "-1.28", "9.0", "4.0", "5.0", "4.83"],
    "Adresse_postale": [None] * 6,
    "Code_postal_et_commune": ["44190#Clisson", "44190#Clisson", "20000#Ajaccio", "07000#Privas", "13001#Marseille", "69001#Lyon"],
    "Periodes_regroupees": ["2026-06-19<->2026-06-21|2026-06-19<->2026-06-21|2026-06-26<->2026-06-28", "2026-06-19<->2026-06-21",
                            "2026-07-01<->2026-07-02", "abc", "2926-01-01<->2926-01-02|2026-05-01<->2026-04-01", "2026-10-16<->2026-10-16"],
    "URI_ID_du_POI": ["e1", "e1", "e2", "e3", "e4", "e5"],
})


def test_categorie():
    assert evenement.categorie(CORE + "CulturalEvent|" + CORE + "Concert|http://schema.org/Event") == "Concert"
    assert evenement.categorie(CORE + "Inconnu") == "autre"


def test_periodes_ecarte_les_invalides():
    p = evenement.periodes("2026-10-16<->2026-10-18|2926-01-01<->2926-01-02|2026-05-01<->2026-04-01|2026-01-01<->2028-01-01|abc")
    assert list(p["date_debut"]) == [date(2026, 10, 16)] and list(p["date_fin"]) == [date(2026, 10, 18)]


def test_nettoyer():
    ev, plages = evenement.nettoyer(BRUT)
    assert list(ev["nom"]) == ["Hellfest", "Concert"]        # doublon, Corse, sans période valide écartés
    assert list(ev["categorie"]) == ["Festival", "Concert"]
    assert len(plages) == 3                                  # Hellfest : 2 périodes distinctes ; Concert : 1
    assert list(plages["evenement"]) == [0, 0, 1]


def test_charger_et_relancer_sans_doublon(db):
    with get_engine().begin() as conn:
        conn.execute(Lieu.__table__.insert(), [{"id": 1, "type": "gare", "source": "gares_voyageurs", "nom": "Clisson", "lat": 47.09, "lon": -1.28}])
    ev, plages = evenement.nettoyer(BRUT)
    ev = evenement.rattacher_aux_gares(ev, evenement.lire_gares())
    assert evenement.charger(ev, plages) == (2, 3) and evenement.charger(ev, plages) == (2, 3)
    with Session(get_engine()) as s:
        compte = lambda m: s.scalar(select(func.count()).select_from(m))
        assert (compte(Evenement), compte(EvenementLieu), compte(EvenementPeriode)) == (2, 2, 3)
        assert s.scalar(select(func.count()).select_from(Lieu).where(Lieu.type == "evenement")) == 2
        assert s.scalar(select(func.count()).select_from(Lieu).where(Lieu.type == "gare")) == 1
        lieu = s.scalar(select(Lieu).where(Lieu.type == "evenement", Lieu.nom == "Hellfest"))
        assert lieu.gare_proche_id == 1 and lieu.commune == "Clisson"
