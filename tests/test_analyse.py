"""Vérifie les chiffres de l'onglet Analyse (lib/analyse.py) sur une base SQLite temporaire."""
import sys
import tempfile
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "migrations"))

from sqlalchemy.orm import Session

import migration
from lib import analyse
from lib.analyse import Filtres
from lib.db.connection import get_engine
from lib.db.models import Evenement, EvenementLieu, EvenementPeriode, Lieu

# Département 13 : 6 sites à 0,5 / 3 / 10 / 20 km, sans gare, et un festival en juillet 2026 ; département 84 : un site à 0,5 km.
LIEUX = [
    dict(id=1, type="gare", nom="Gare", departement="13", lat=43.3, lon=5.4),
    dict(id=10, type="culture", nom="Musée de l'Olivier", departement="13", distance_gare_km=0.5, gare_proche_id=1),
    dict(id=11, type="culture", nom="Musée B", departement="13", distance_gare_km=3.0, gare_proche_id=1),
    dict(id=12, type="tourisme", nom="Calanque", departement="13", distance_gare_km=10.0, gare_proche_id=1),
    dict(id=13, type="tourisme", nom="Mont", departement="13", distance_gare_km=20.0, gare_proche_id=1),
    dict(id=14, type="tourisme", nom="Île", departement="13"),
    dict(id=15, type="evenement", nom="Festival d'été", departement="13", distance_gare_km=0.5, gare_proche_id=1),
    dict(id=20, type="culture", nom="Théâtre", departement="84", distance_gare_km=0.5, gare_proche_id=1),
    dict(id=30, type="station_velo", nom="Vélo", departement="13", distance_gare_km=0.1),
]


@pytest.fixture
def engine(monkeypatch):
    with tempfile.TemporaryDirectory() as dossier:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{dossier}/test.db")
        migration.migrate()
        with Session(get_engine()) as session:
            session.add_all([Lieu(**l) for l in LIEUX])
            session.add(Evenement(id=1, nom="Festival d'été"))
            session.add(EvenementLieu(evenement_id=1, lieu_id=15))
            session.add(EvenementPeriode(evenement_id=1, date_debut=date(2026, 7, 10), date_fin=date(2026, 7, 20)))
            session.commit()
        yield get_engine()


def test_indicateurs_sans_stations_velo_ni_gares(engine):
    kpi = analyse.indicateurs(engine, Filtres())
    assert kpi["total"] == 7                                  # ni la gare ni la station vélo
    assert kpi["sans_voiture"] == 4 and kpi["part_sans_voiture"] == round(100 * 4 / 7, 1)
    assert kpi["part_zones_blanches"] == round(100 * 2 / 7, 1)  # 20 km et sans gare
    assert kpi["part_sans_voiture"] + kpi["part_zones_blanches"] != 100


def test_iaf_pondere_comme_l_eda_et_france_calculee(engine):
    deps, france = analyse.iaf_departements(engine, Filtres(categorie="tous"))
    assert list(deps["departement"]) == ["13"]                # le 84 a moins de 5 sites
    # 0,5 km → 1 ; 3 km → 0,5 ; 10 km → 0,1 ; 20 km → 0,1 ; sans gare → 0 ; festival 0,5 km → 1
    assert deps.iloc[0]["iaf"] == round(100 * 2.7 / 6, 1)
    assert france == round(100 * 3.7 / 7, 1)
    _, france_13 = analyse.iaf_departements(engine, Filtres(departements=["13"]))
    assert france_13 == france                                 # la référence France ignore le département choisi


def test_destination_avec_apostrophe_et_seuil(engine):
    f = Filtres(destination="Musée de l'Olivier")
    assert analyse.indicateurs(engine, f)["total"] == 1
    deps, _ = analyse.iaf_departements(engine, f)
    assert list(deps["sites"]) == [1]                           # un seul site : le département reste affiché
    assert analyse.chercher_sites(engine, "de l'oli") == ["Musée de l'Olivier"]
    assert analyse.chercher_sites(engine, "m") == []            # 2 lettres minimum


def test_periode_ne_garde_que_les_evenements_qui_la_croisent(engine):
    assert analyse.indicateurs(engine, Filtres(categorie="evenement", debut="2026-07-01", fin="2026-07-31"))["total"] == 1
    assert analyse.indicateurs(engine, Filtres(categorie="evenement", debut="2026-09-01", fin="2026-12-31")) is None
    assert analyse.indicateurs(engine, Filtres(debut="2026-09-01", fin="2026-12-31"))["total"] == 6   # culture et tourisme restent


def test_saisonnalite_filtree_et_dans_l_ordre(engine):
    saison = analyse.saisonnalite(engine, Filtres(debut="2026-01-01", fin="2026-12-31"))
    assert saison.to_dict("records") == [{"mois": "Juil 2026", "evenements": 1}]
    assert analyse.saisonnalite(engine, Filtres(departements=["84"])).empty
    assert analyse.saisonnalite(engine, Filtres(categorie="culture")).empty


def test_plan_action_et_tranches(engine):
    plan = analyse.plan_action(engine, Filtres(departements=["13"]), mode="pires", limite=2)
    assert list(plan["SITE TOURISTIQUE"]) == ["Mont", "Calanque"]
    assert list(plan["PRIORITÉ"]) == ["Urgente", "Élevée"]
    tranches = analyse.tranches_distance(engine, Filtres(categorie="tourisme"))
    assert dict(zip(tranches["tranche"], tranches["sites"])) == {"5-15 km (Navette)": 1, "> 15 km (Voiture)": 2}
