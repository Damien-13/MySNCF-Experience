"""Vérifie la transformation des gares (src/transformation/gare.py) sur une base SQLite temporaire, supprimée à la fin."""
import sys
import tempfile
from datetime import time
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "migrations"))
sys.path.insert(0, str(ROOT / "src" / "transformation"))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import gare
import migration
from lib.db.connection import get_engine
from lib.db.models import Gare, GareHoraire, Lieu


@pytest.fixture
def db(monkeypatch):
    with tempfile.TemporaryDirectory() as folder:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{folder}/test.db")
        migration.migrate()
        yield


GARES = pd.DataFrame({
    "Nom_Gare": ["Abancourt", "Aéroport CDG 2", "Ajaccio", "Sans position"],
    "Position géographique": ["49.6852237, 1.7743058", "49.003652, 2.570892", "41.92, 8.74", "n/a"],
    "Code commune": ["60001", "93073", "2A004", "01001"],
    "Code_UIC": ["87313759", "87271494;87001479", "87773002", "87000000"],
})
HORAIRES = pd.DataFrame({
    "UIC": ["0087313759", "0087313759", "0087001479", "0087116137", "0087313759"],
    "Jour de la semaine": ["Lundi", "Dimanche", "Mardi", "Jeudi", "Samedi"],
    "Horaire en jour normal": ["05:45-20:45", "07:00-21:45", "05:00-01:00", "05:15-12:30", "Fermée"],
})


def test_nettoyer_gares():
    out = gare.nettoyer_gares(GARES)
    assert list(out["nom"]) == ["Abancourt", "Aéroport CDG 2", "Ajaccio"]   # position illisible écartée
    assert list(out["code_uic"]) == ["87313759", "87271494", "87773002"]
    assert out.loc[1, "uic"] == ["87271494", "87001479"]
    assert list(out["departement"]) == ["60", "93", "2A"]
    assert out.loc[0, "lat"] == pytest.approx(49.6852237) and out.loc[0, "lon"] == pytest.approx(1.7743058)


def test_nettoyer_horaires_ecarte_illisibles_et_garde_minuit():
    out = gare.nettoyer_horaires(HORAIRES)
    assert len(out) == 4                                                    # « Fermée » écarté
    nuit = out[out["uic"] == "87001479"].iloc[0]
    assert nuit["jour"] == 1 and nuit["heure_ouverture"] == time(5, 0) and nuit["heure_fermeture"] == time(1, 0)


def test_associer_horaires_par_n_importe_quel_uic():
    gares = gare.nettoyer_gares(GARES)
    lies, orphelines = gare.associer_horaires(gares, gare.nettoyer_horaires(HORAIRES))
    assert orphelines == 1                                                  # 87116137 n'est pas une gare connue
    assert set(lies["code_uic"]) == {"87313759", "87271494"}                # 87001479 → gare de CDG


def test_charger_et_relancer_sans_doublon(db):
    gares = gare.nettoyer_gares(GARES)
    horaires, _ = gare.associer_horaires(gares, gare.nettoyer_horaires(HORAIRES))
    assert gare.charger(gares, horaires) == (3, 3)
    assert gare.charger(gares, horaires) == (3, 3)                          # deuxième passage : remplacement, pas ajout
    with Session(get_engine()) as s:
        assert s.scalar(select(func.count()).select_from(Lieu)) == 3
        assert s.scalar(select(func.count()).select_from(Gare)) == 3
        assert s.scalar(select(func.count()).select_from(GareHoraire)) == 3
        lieu = s.scalar(select(Lieu).join(Gare, Gare.lieu_id == Lieu.id).where(Gare.code_uic == "87773002"))
        assert lieu.nom == "Ajaccio" and lieu.type == "gare" and lieu.source == gare.SOURCE


def test_charger_ne_touche_pas_aux_autres_lieux(db):
    with get_engine().begin() as conn:
        conn.execute(Lieu.__table__.insert(), [{"type": "culture", "source": "basilic", "nom": "Musée"}])
    gares = gare.nettoyer_gares(GARES)
    gare.charger(gares, gare.associer_horaires(gares, gare.nettoyer_horaires(HORAIRES))[0])
    with Session(get_engine()) as s:
        assert s.scalar(select(func.count()).select_from(Lieu).where(Lieu.type == "culture")) == 1


def test_recharger_garde_les_identifiants_des_gares(db):
    gares = gare.nettoyer_gares(GARES)
    horaires, _ = gare.associer_horaires(gares, gare.nettoyer_horaires(HORAIRES))
    gare.charger(gares, horaires)
    with Session(get_engine()) as s:
        avant = {g.code_uic: g.lieu_id for g in s.scalars(select(Gare))}
    # une gare du fichier disparaît, une autre change de nom : les autres gardent leur identifiant, rien ne se décale
    suivant = gares[gares["code_uic"] != "87773002"].assign(nom=lambda d: d["nom"].where(d["code_uic"] != "87313759", "Abancourt (renommée)"))
    gare.charger(suivant, horaires[horaires["code_uic"].isin(suivant["code_uic"])])
    with Session(get_engine()) as s:
        apres = {g.code_uic: g.lieu_id for g in s.scalars(select(Gare))}
        assert apres == {c: i for c, i in avant.items() if c != "87773002"}
        assert s.get(Lieu, avant["87313759"]).nom == "Abancourt (renommée)"
        assert s.get(Lieu, avant["87773002"]) is None
        assert s.scalar(select(func.count()).select_from(Lieu)) == 2
