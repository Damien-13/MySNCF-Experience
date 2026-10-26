"""Vérifie l'accès en transport en commun des sites (src/transformation/acces_tc.py) sur des positions synthétiques et une base SQLite temporaire."""
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "migrations"))
sys.path.insert(0, str(ROOT / "src" / "transformation"))

from sqlalchemy import select
from sqlalchemy.orm import Session

import acces_tc
import migration
from lib.db.connection import get_engine
from lib.db.models import Lieu

# Gare à (5.0, 45.0). L1 : un arrêt à 1 km de la gare et un arrêt à 1 km du site « direct ». L2 : seulement près du site « autre ligne ».
# L3 : part à 100 m du 2e arrêt de L1 (correspondance) et va au site « correspondance ». Environ 77 km par degré de longitude (projection de lib/reseau_ferre.py).
GARE = (5.0, 45.0)
ARRETS = pd.DataFrame([
    {"ligne_id": "L1", "lon": 5.0127, "lat": 45.0},
    {"ligne_id": "L1", "lon": 5.1127, "lat": 45.0},
    {"ligne_id": "L2", "lon": 5.2, "lat": 45.1},
    {"ligne_id": "L3", "lon": 5.114, "lat": 45.0},
    {"ligne_id": "L3", "lon": 5.3, "lat": 45.2},
])
SITES = pd.DataFrame({
    "lon": [5.1, 5.2, 5.4, 5.1, 5.3],
    "lat": [45.0, 45.1, 45.0, 45.0, 45.2],
    "gare_lon": [GARE[0], GARE[0], GARE[0], None, GARE[0]],
    "gare_lat": [GARE[1], GARE[1], GARE[1], None, GARE[1]],
}, index=[1, 2, 3, 4, 5])                  # direct, autre ligne, aucun arrêt, sans gare connue, correspondance


def test_acces_direct_ou_avec_une_correspondance():
    assert acces_tc.acces(SITES, ARRETS).to_dict() == {1: True, 2: False, 3: False, 4: False, 5: True}
    assert acces_tc.acces(SITES, ARRETS, correspondances_max=0).to_dict() == {1: True, 2: False, 3: False, 4: False, 5: False}


def test_marche_limitee_a_1_5_km():
    loin = SITES.loc[[1]].assign(lon=5.114 + 1.6 / acces_tc.KM_PAR_DEGRE_LON)      # site à 1,6 km à l'est du premier arrêt de L3, plus loin encore de L1
    assert not acces_tc.acces(loin, ARRETS).any()


def test_sans_arret_ni_site():
    assert not acces_tc.acces(SITES, ARRETS.iloc[0:0]).any()
    assert acces_tc.acces(SITES.iloc[0:0], ARRETS).empty


def test_charger_ecrit_tous_les_sites(monkeypatch):
    with tempfile.TemporaryDirectory() as dossier:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{dossier}/test.db")
        migration.migrate()
        engine = get_engine()
        with Session(engine) as session:
            session.add_all([Lieu(id=1, type="culture"), Lieu(id=2, type="tourisme", acces_tc=True), Lieu(id=3, type="gare")])
            session.commit()
        assert acces_tc.charger(pd.Series({1: True, 2: False}), engine) == 1
        with Session(engine) as session:
            assert dict(session.execute(select(Lieu.id, Lieu.acces_tc)).all()) == {1: True, 2: False, 3: None}   # la gare n'est pas un site
        engine.dispose()
