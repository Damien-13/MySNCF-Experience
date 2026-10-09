"""Vérifie la logique de l'onglet Itinéraire voyageur (lib/itineraire.py) sur une base SQLite temporaire, l'API Navitia étant simulée."""
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "migrations"))

from sqlalchemy.orm import Session

import migration
from lib import itineraire, navitia
from lib.db.connection import get_engine
from lib.db.models import Gare, Lieu
from lib.reseau_ferre import chemin, construire_reseau

# Deux gares sur une même voie droite ; un château à 1 km de la seconde ; un festival plus loin ; des stations et un arrêt de bus près de la seconde.
GARE_A = dict(id=1, type="gare", nom="Gare A", lat=48.0, lon=2.0)
GARE_B = dict(id=2, type="gare", nom="Gare B", lat=48.0, lon=2.2)
LIEUX = [
    GARE_A, GARE_B,
    dict(id=10, type="culture", nom="Château de Test", commune="Testville", lat=48.009, lon=2.2, gare_proche_id=2, distance_gare_km=1.0),
    dict(id=11, type="evenement", nom="Festival de Test", commune="Testville", lat=48.03, lon=2.2, gare_proche_id=2, distance_gare_km=3.3),
    dict(id=12, type="culture", nom="Musée Lointain", commune="Loin", lat=48.2, lon=2.2, gare_proche_id=2, distance_gare_km=22.0),
    dict(id=20, type="station_velo", nom="Vélo 1", lat=48.001, lon=2.2),
    dict(id=21, type="arret_bus", nom="Bus 1", lat=48.0, lon=2.201),
]
VOIE = [[[2.0, 48.0], [2.1, 48.0], [2.2, 48.0]]]


@pytest.fixture
def engine(monkeypatch):
    with tempfile.TemporaryDirectory() as dossier:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{dossier}/test.db")
        migration.migrate()
        with Session(get_engine()) as session:
            session.add_all([Lieu(**l) for l in LIEUX])
            session.add_all([Gare(lieu_id=1, code_uic="87000001"), Gare(lieu_id=2, code_uic="87000002")])
            session.commit()
        yield get_engine()


def _trajet(de, vers):
    return {"duree_s": 3600, "correspondances": 0, "depart": datetime(2026, 10, 12, 8, 0), "arrivee": datetime(2026, 10, 12, 9, 0), "co2_g": 1500.0,
            "sections": [{"type": "public_transport", "de_lonlat": de, "vers_lonlat": vers, "ligne": "TGV INOUI", "numero": "6101"}]}


def test_options_gares_et_recherche_de_destinations(engine):
    assert [o["label"] for o in itineraire.options_gares(engine)] == ["Gare A", "Gare B"]
    assert [o["value"] for o in itineraire.chercher_destinations("test", "culture", engine)] == [10]            # le festival n'est pas de la culture
    assert [o["value"] for o in itineraire.chercher_destinations("test", "evenement", engine)] == [11]
    assert [o["label"] for o in itineraire.chercher_destinations("Château", "tous", engine)] == ["Château de Test (Testville)"]
    assert 12 in [o["value"] for o in itineraire.chercher_destinations("", "culture", engine, inclure=12, limite=1)]   # le lieu déjà choisi reste dans la liste


def test_dernier_km_selon_distance_et_alentours():
    rien, proches = {"velo": 0, "bus": 0}, {"velo": 3, "bus": 1}
    assert itineraire.dernier_km(1.0, rien)[0] == "Marche à pied"
    assert itineraire.dernier_km(3.0, proches)[0] == "Vélo / Bus"
    assert itineraire.dernier_km(3.0, rien)[0] == "Voiture / Taxi"                    # entre 1,5 et 5 km sans vélo ni bus près de la gare
    assert itineraire.dernier_km(12.0, proches)[0] == "Voiture / Taxi"
    assert itineraire.dernier_km(None, rien)[0] == "--"


def test_alentours_et_pois(engine):
    assert itineraire.alentours(engine, 48.0, 2.2) == {"velo": 1, "bus": 1}
    pois = itineraire.pois_autour(engine, 48.009, 2.2, "culture")
    assert list(pois["id"]) == [10]                                                    # le musée est à 21 km, le festival n'est pas de la culture
    assert set(itineraire.pois_autour(engine, 48.009, 2.2, "tous")["id"]) == {10, 11}


def test_quand_depuis():
    maintenant = datetime(2026, 10, 9, 10, 30, 15, 123)
    assert itineraire.quand_depuis("2026-10-12", "07:00", maintenant) == datetime(2026, 10, 12, 7, 0)
    assert itineraire.quand_depuis("2026-10-12", None, maintenant) == datetime(2026, 10, 12, 8, 0)
    assert itineraire.quand_depuis("2026-10-09", None, maintenant) == datetime(2026, 10, 9, 10, 30, 15)       # aujourd'hui : maintenant


def test_chemin_suit_la_voie_ou_se_replie_en_ligne_droite():
    reseau = construire_reseau(VOIE)
    points, sur_voie = chemin(reseau, (2.0, 48.0001), (2.2, 48.0001))
    assert sur_voie and [2.1, 48.0] in points
    assert chemin(reseau, (2.0, 48.0001), (9.0, 40.0)) == ([[2.0, 48.0001], [9.0, 40.0]], False)             # gare à des centaines de km des voies
    assert chemin(None, (2.0, 48.0), (2.2, 48.0)) == ([[2.0, 48.0], [2.2, 48.0]], False)                     # sans réseau en base


def test_style_ligne_donne_une_couleur_et_un_motif_par_service():
    styles = {nom: itineraire.style_ligne(s) for nom, s in {
        "inoui": {"ligne": "TGV INOUI", "mode_physique": "Train grande vitesse"},
        "ouigo": {"ligne": "OUIGO"},
        "ter": {"ligne": "ZOU !", "reseau": "ZOU !", "mode_physique": "Train"},
        "intercites": {"ligne": "INTERCITES"},
        "rer": {"ligne": "RER"},
        "bus": {"ligne": "ZOU !", "mode_physique": "Autocar"},
        "eurostar": {"ligne": "Eurostar"},
        "inconnu": {},
    }.items()}
    assert {nom: st["cle"] for nom, st in styles.items()} == {nom: nom for nom in styles}
    assert len({(st["couleur"], st["tirets"]) for st in styles.values()}) == len(styles)          # aucun service ne ressemble à un autre
    assert styles["inoui"]["tirets"] is None and styles["ouigo"]["tirets"]


def test_tracer_trajet_un_trace_par_train_et_liaison_directe_sans_trajet():
    reseau = construire_reseau(VOIE)
    traces = itineraire.tracer_trajet(_trajet((2.0, 48.0), (2.2, 48.0)), reseau, (2.0, 48.0), (2.2, 48.0))
    assert len(traces) == 1 and traces[0]["sur_voie"] and traces[0]["libelle"] == "TGV INOUI 6101"
    assert traces[0]["points"][0] == [48.0, 2.0]                                                   # [lat, lon] pour la carte
    direct = itineraire.tracer_trajet(None, reseau, (2.0, 48.0), (2.2, 48.0))
    assert len(direct) == 1 and direct[0]["libelle"] == "Liaison directe"


def test_tracer_trajet_marche_et_dernier_km():
    reseau = construire_reseau(VOIE)
    trajet = _trajet((2.0, 48.0), (2.2, 48.0))
    trajet["sections"].append({"type": "transfer", "mode": "walking", "duree_s": 240, "de_lonlat": (2.2, 48.0), "vers_lonlat": (2.2, 48.002)})
    trajet["sections"].append({"type": "transfer", "mode": "walking", "duree_s": 8, "de_lonlat": (2.2, 48.0), "vers_lonlat": (2.2, 48.0001)})      # trop court pour être tracé
    etapes = itineraire.tracer_trajet(trajet, reseau, (2.0, 48.0), (2.2, 48.0))
    assert [(e["marche"], e["libelle"]) for e in etapes] == [(False, "TGV INOUI 6101"), (True, "À pied · 4 min")]
    assert etapes[1]["style"]["tirets"] != etapes[0]["style"]["tirets"]                    # un autre motif à pied qu'en train
    assert {itineraire.style_dernier_km(m)["tirets"] for m in ("Marche à pied", "Vélo / Bus", "Voiture / Taxi")} == {"1 9", "10 7", "18 8"}


def test_car_passe_par_ses_arrets_sans_suivre_les_rails():
    reseau = construire_reseau(VOIE)
    car = {"type": "public_transport", "mode": "train", "mode_physique": "Autocar", "ligne": "TER", "numero": "99", "duree_s": 1800, "de_lonlat": (2.0, 48.0),
           "vers_lonlat": (2.2, 48.0), "arrets_lonlat": [(2.0, 48.0), (2.05, 48.02), (2.2, 48.0)]}
    etapes = itineraire.tracer_trajet({"sections": [car]}, reseau, (2.0, 48.0), (2.2, 48.0))
    assert etapes[0]["points"] == [[48.0, 2.0], [48.02, 2.05], [48.0, 2.2]] and etapes[0]["style"]["cle"] == "bus" and not etapes[0]["sur_voie"]
    car["arrets_lonlat"] = []                                                                     # sans liste d'arrêts : droit de départ à arrivée
    assert itineraire.tracer_trajet({"sections": [car]}, reseau, (2.0, 48.0), (2.2, 48.0))[0]["points"] == [[48.0, 2.0], [48.0, 2.2]]


def test_filtre_culture_ne_garde_que_la_culture(engine):
    assert set(itineraire.pois_autour(engine, 48.009, 2.2, "culture")["type"]) == {"culture"}
    assert {o["value"] for o in itineraire.chercher_destinations("", "culture", engine, limite=100)} == {10, 12}


def test_rechercher_assemble_tout(engine, monkeypatch):
    appels = []
    monkeypatch.setattr(navitia, "itineraires", lambda a, b, quand=None, nombre=3: appels.append((a, b)) or [_trajet((2.0, 48.0), (2.2, 48.0))])
    r = itineraire.rechercher(1, 10, quand=datetime(2026, 10, 12, 8), retour=datetime(2026, 10, 14, 18), engine=engine)
    assert appels == [("stop_area:SNCF:87000001", "stop_area:SNCF:87000002"), ("stop_area:SNCF:87000002", "stop_area:SNCF:87000001")]
    assert r["gare_arrivee"]["nom"] == "Gare B" and r["distance_km"] == 1.0 and r["faisable"] is True
    assert r["dernier_km"][0] == "Marche à pied" and r["alentours"] == {"velo": 1, "bus": 1}
    assert len(r["trajets"]) == 1 and len(r["trajets_retour"]) == 1 and r["erreur_api"] is None


def test_rechercher_sans_retour_ni_api(engine, monkeypatch):
    def en_panne(*args, **kwargs):
        raise RuntimeError("API SNCF injoignable (ConnectionError)")
    monkeypatch.setattr(navitia, "itineraires", en_panne)
    r = itineraire.rechercher(1, 12, engine=engine)
    assert r["erreur_api"] == "API SNCF injoignable (ConnectionError)" and r["trajets"] == [] and r["trajets_retour"] == []
    assert r["distance_km"] == 22.0 and r["faisable"] is False and r["dernier_km"][0] == "Voiture / Taxi"     # les KPI restent calculés sans l'API


def test_rechercher_meme_gare_ne_appelle_pas_l_api(engine, monkeypatch):
    monkeypatch.setattr(navitia, "itineraires", lambda *a, **k: pytest.fail("l'API ne doit pas être appelée"))
    r = itineraire.rechercher(2, 10, engine=engine)                    # le château est à côté de la gare B, qui est aussi le départ
    assert r["meme_gare"] and r["trajets"] == [] and r["distance_km"] == 1.0


def test_rechercher_lieu_inconnu(engine):
    assert itineraire.rechercher(1, 999, engine=engine) is None
