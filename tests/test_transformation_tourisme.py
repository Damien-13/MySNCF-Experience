"""Vérifie la transformation du tourisme (src/transformation/tourisme.py, geo.py) sur une base SQLite temporaire, supprimée à la fin."""
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
import tourisme
from lib.db.connection import get_engine
from lib.db.models import Lieu

CORE = "https://www.datatourisme.fr/ontology/core#"


@pytest.fixture
def db(monkeypatch):
    with tempfile.TemporaryDirectory() as folder:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{folder}/test.db")
        migration.migrate()
        yield


BRUT = pd.DataFrame({
    "Nom_du_POI": ["Château A", "Château A bis", "Hôtel B", "Parc C", "Parc Corse", "Plage Réunion", "Musée Chine", "Falaise D"],
    "Categories_de_POI": [CORE + "CulturalSite|" + CORE + "Museum", CORE + "CulturalSite", CORE + "Hotel|" + CORE + "Accommodation",
                          CORE + "ParkAndGarden", CORE + "NaturalHeritage", CORE + "Landform", CORE + "CulturalSite", CORE + "Landform|" + CORE + "NaturalHeritage"],
    "Latitude": ["47.59", "47.59", "45.0", "45.76", "42.0", "-21.0", "30.0", "44.5"],
    "Longitude": ["1.33", "1.33", "4.0", "4.83", "9.0", "55.4", "120.0", "6.2"],
    "Adresse_postale": ["r. 1", "r. 1", None, "pl. 2", None, None, None, None],
    "Code_postal_et_commune": ["41250#Chambord", "41250#Chambord", "07000#Privas", "69001#Lyon", "20000#Ajaccio", "97400#Saint-Denis", "99999#X", "05000#Gap|05100#Autre"],
    "URI_ID_du_POI": ["u1", "u1", "u2", "u3", "u4", "u5", "u6", "u7"],
})


def test_departement_et_commune():
    dep, com = geo.departement_et_commune(["37250#Veigné", "97400#Saint-Denis", "20000#Ajaccio", "abc#X", None, "05000#Gap|05100#Autre"])
    assert list(dep) == ["37", "974", "20", "", "", "05"]
    assert list(com)[:3] == ["Veigné", "Saint-Denis", "Ajaccio"] and com[5] == "Gap"


def test_lire_ne_garde_que_les_attractions(tmp_path):
    fichier = tmp_path / "place.csv"
    BRUT.to_csv(fichier, index=False)
    gardees, lues = tourisme.lire(fichier)
    assert lues == 8 and "Hôtel B" not in set(gardees["Nom_du_POI"]) and len(gardees) == 7


def test_nettoyer():
    out = tourisme.nettoyer(BRUT[BRUT["Nom_du_POI"] != "Hôtel B"])
    assert list(out["nom"]) == ["Château A", "Parc C", "Falaise D"]       # doublon d'URI, Corse, outre-mer, étranger écartés
    assert list(out["departement"]) == ["41", "69", "05"]
    assert out.loc[0, "commune"] == "Chambord"


def test_charger_remplace_et_ne_touche_pas_aux_autres_lieux(db):
    with get_engine().begin() as conn:
        conn.execute(Lieu.__table__.insert(), [
            {"id": 1, "type": "gare", "source": "gares_voyageurs", "nom": "Blois", "lat": 47.58, "lon": 1.34},
            {"id": 2, "type": "culture", "source": "basilic", "nom": "Musée", "lat": 48.0, "lon": 2.0}])
    lieux = tourisme.rattacher_aux_gares(tourisme.nettoyer(BRUT[BRUT["Nom_du_POI"] != "Hôtel B"]), tourisme.lire_gares())
    assert tourisme.charger(lieux) == 3 and tourisme.charger(lieux) == 3
    with Session(get_engine()) as s:
        assert s.scalar(select(func.count()).select_from(Lieu).where(Lieu.type == "tourisme")) == 3
        assert s.scalar(select(func.count()).select_from(Lieu)) == 5
        assert s.scalar(select(Lieu).where(Lieu.nom == "Château A")).gare_proche_id == 1
