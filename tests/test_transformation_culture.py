"""Vérifie la transformation de la culture (src/transformation/culture.py, geo.py) sur une base SQLite temporaire, supprimée à la fin."""
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "migrations"))
sys.path.insert(0, str(ROOT / "src" / "transformation"))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import culture
import geo
import migration
from lib.db.connection import get_engine
from lib.db.models import Lieu


@pytest.fixture
def db(monkeypatch):
    with tempfile.TemporaryDirectory() as folder:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{folder}/test.db")
        migration.migrate()
        yield


BRUT = pd.DataFrame({
    "Nom": ["Château A", "Château A", "Musée B", "Case créole", "", "Phare C", "Musée Lu Xun", "Citadelle"],
    "Adresse": ["r. 1", "r. 1", None, "r. 2", "r. 3", "quai", None, "haut"],
    "libelle_geographique": ["Blois", "Blois", "Lyon", "Saint-Denis", "X", "Ajaccio", "Shaoxing, Chine", "Bonifacio"],
    "N_Département": ["41", "41", "69", "974", "01", "2A", None, "2B"],
    "Latitude": ["47.59", "47.59", "45.76", "-21.0", "46.0", "abc", "30.0", "41.4"],
    "Longitude": ["1.33", "1.33", "4.83", "55.4", "5.0", "8.7", "120.5", "9.1"],
})


def test_haversine_paris_lyon():
    indices, distances = geo.plus_proche([48.8566], [2.3522], [45.76, 43.30], [4.83, 5.37])
    assert indices[0] == 0 and distances[0] == pytest.approx(392, abs=3)    # Paris → Lyon ≈ 392 km


def test_plus_proche_sans_cible():
    indices, distances = geo.plus_proche([48.0], [2.0], [], [])
    assert indices[0] == -1 and np.isnan(distances[0])


def test_plus_proche_par_paquets(monkeypatch):
    monkeypatch.setattr(geo, "PAQUET", 2)
    indices, _ = geo.plus_proche([48, 45, 43, 47, 44], [2, 5, 5, 1, 4], [48.1, 43.1], [2.1, 5.1])
    assert list(indices) == [0, 1, 1, 0, 1]


def test_nettoyer():
    out = culture.nettoyer(BRUT)
    assert list(out["nom"]) == ["Château A", "Musée B"]       # doublon, outre-mer, Corse, étranger, sans nom et position invalide écartés
    assert list(out["departement"]) == ["41", "69"]


def test_rattacher_aux_gares():
    lieux = culture.nettoyer(BRUT)
    gares = pd.DataFrame({"id": [10, 20], "lat": [47.58, 45.75], "lon": [1.34, 4.85]})
    out = culture.rattacher_aux_gares(lieux, gares)
    assert list(out["gare_proche_id"]) == [10, 20]
    assert out["distance_gare_km"].between(0, 5).all()


def test_charger_remplace_et_ne_touche_pas_aux_gares(db):
    with get_engine().begin() as conn:
        conn.execute(Lieu.__table__.insert(), [{"id": 1, "type": "gare", "source": "gares_voyageurs", "nom": "Blois", "lat": 47.58, "lon": 1.34}])
    lieux = culture.rattacher_aux_gares(culture.nettoyer(BRUT), culture.lire_gares())
    assert culture.charger(lieux) == 2
    assert culture.charger(lieux) == 2                                      # relance : remplacement, pas ajout
    with Session(get_engine()) as s:
        assert s.scalar(select(func.count()).select_from(Lieu).where(Lieu.type == "culture")) == 2
        assert s.scalar(select(func.count()).select_from(Lieu).where(Lieu.type == "gare")) == 1
        blois = s.scalar(select(Lieu).where(Lieu.nom == "Château A"))
        assert blois.gare_proche_id == 1 and blois.commune == "Blois" and blois.source == "basilic"
