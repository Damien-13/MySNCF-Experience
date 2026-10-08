"""Vérifie la transformation des stations vélo (src/transformation/velo.py) sur une base SQLite temporaire, supprimée à la fin."""
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

import geo
import migration
import velo
from lib.db.connection import get_engine
from lib.db.models import Lieu, StationVelo


@pytest.fixture
def db(monkeypatch):
    with tempfile.TemporaryDirectory() as folder:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{folder}/test.db")
        migration.migrate()
        yield


STATIONNEMENT = pd.DataFrame({
    "id_osm": ["node/1", "node/1", "node/2", "node/3", "node/4", "node/5", None, None],
    "code_com": ["41018", "41018", "69123", "2A004", None, "97411", "37003", "37003"],
    "coordonneesxy": ["[1.33,47.58]", "[1.33,47.58]", "[4.83,45.76]", "[9.0,41.9]", "[9.1,42.2]", "[55.4,-21.0]", "[0.98,47.42]", "[0.99,47.43]"],
    "capacite": ["8", "8", "0", "10", None, "5", "7", "3"],
})


def test_stationnement_et_nettoyage():
    brut = velo.stationnement(STATIONNEMENT, "velo_stationnement_osm")
    assert len(brut) == 7                                              # node/1 en double retiré ; les id_osm vides ne sont pas des doublons
    out = velo.nettoyer(brut)
    assert list(out["lat"]) == [47.58, 45.76, 47.42, 47.43]            # Corse (code ET position), outre-mer écartés
    assert out.loc[1, "capacite"] != out.loc[1, "capacite"]            # capacité 0 → vide
    assert list(out["departement"]) == ["41", "69", "37", "37"] and set(out["reseau"]) == {"stationnement"}


def test_corse_ecartee_meme_sans_departement():
    assert not geo.dans_la_france_continentale([42.2], [9.1]).iloc[0]   # nord de la Corse
    assert geo.dans_la_france_continentale([43.28], [5.37]).iloc[0]     # Marseille


def test_velib_et_velov():
    v = velo.velib(pd.DataFrame({"Nom station": ["Cassini"], "Nom communes équipées": ["Paris"], "Code INSEE communes équipées": ["75056"],
                                 "Coordonnées géographiques": ["48.837525, 2.336035"], "Capacité de la station": ["25"]}))
    assert v.loc[0, "nom"] == "Cassini" and v.loc[0, "reseau"] == "velib" and v.loc[0, "departement"] == "75" and v.loc[0, "capacite"] == 25
    lyon = velo.velov(pd.DataFrame({"name": ["4025 - CHAZIÈRE"], "commune": ["Lyon 4e Arrondissement"], "code_insee": ["69384"],
                                    "lat": ["45.775425"], "lng": ["4.817888"], "bike_stands": ["20"]}))
    assert lyon.loc[0, "nom"] == "CHAZIÈRE" and lyon.loc[0, "reseau"] == "velov" and lyon.loc[0, "lon"] == pytest.approx(4.817888)


def test_charger_remplace_et_ne_touche_pas_aux_autres_lieux(db):
    with get_engine().begin() as conn:
        conn.execute(Lieu.__table__.insert(), [{"id": 1, "type": "gare", "source": "gares_voyageurs", "nom": "Blois", "lat": 47.58, "lon": 1.34}])
    stations = velo.nettoyer(velo.stationnement(STATIONNEMENT, "velo_stationnement_osm"))
    stations = velo.rattacher_aux_gares(stations, velo.lire_gares())
    assert velo.charger(stations) == 4 and velo.charger(stations) == 4        # relance : remplacement, pas ajout
    with Session(get_engine()) as s:
        assert s.scalar(select(func.count()).select_from(Lieu).where(Lieu.type == "station_velo")) == 4
        assert s.scalar(select(func.count()).select_from(StationVelo)) == 4
        assert s.scalar(select(func.count()).select_from(Lieu).where(Lieu.type == "gare")) == 1
        blois = s.scalar(select(StationVelo).join(Lieu, Lieu.id == StationVelo.lieu_id).where(Lieu.departement == "41"))
        assert blois.capacite == 8 and blois.reseau == "stationnement"
        assert s.get(Lieu, blois.lieu_id).gare_proche_id == 1
        sans_capacite = s.scalar(select(StationVelo).join(Lieu, Lieu.id == StationVelo.lieu_id).where(Lieu.departement == "69"))
        assert sans_capacite.capacite is None
