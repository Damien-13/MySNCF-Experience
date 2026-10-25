"""Vérifie le choix des gares et l'acheminement en car jusqu'à une gare relais (lib/acheminement.py), et leur usage par la recherche
d'itinéraire (lib/itineraire.py), sur une base SQLite temporaire ; l'API SNCF est simulée."""
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "migrations"))

from sqlalchemy.orm import Session

import migration
from lib import acheminement, itineraire, navitia
from lib.db.connection import get_engine
from lib.db.models import Arret, Calendrier, Circulation, Gare, Lieu, Ligne, Passage, Reseau

JOUR = date.today() + timedelta(days=1)
# Aix centre (1) sans train pour Paris, Aix TGV (2) à 14 km avec un TGV pour Paris Gare de Lyon (3) ; une gare RER à Paris (4) sans train depuis Aix.
# La navette de car relie un arrêt devant la gare d'Aix (20) à un arrêt devant Aix TGV (21) à 13:10 et à 13:40. Le Louvre est à Paris.
LIEUX = [
    dict(id=1, type="gare", nom="Aix-en-Provence", lat=43.5229, lon=5.4453),
    dict(id=2, type="gare", nom="Aix-en-Provence TGV", lat=43.4552, lon=5.3175),
    dict(id=3, type="gare", nom="Paris Gare de Lyon", lat=48.8443, lon=2.3744),
    dict(id=4, type="gare", nom="Saint-Michel Notre-Dame", lat=48.8534, lon=2.3466),
    dict(id=20, type="arret_bus", nom="Gare Routière", lat=43.5232, lon=5.4450),
    dict(id=21, type="arret_bus", nom="Gare TGV", lat=43.4555, lon=5.3172),
    dict(id=30, type="culture", nom="Musée du Louvre", commune="Paris", departement="75", lat=48.8606, lon=2.3376, gare_proche_id=4, distance_gare_km=1.2),
    dict(id=31, type="tourisme", nom="Tour Eiffel", commune="Paris", departement="75", lat=48.8584, lon=2.2945, gare_proche_id=4, distance_gare_km=0.5),
    dict(id=32, type="tourisme", nom="La tour Eiffel", commune="Paris", departement="75", lat=48.8584, lon=2.2946, gare_proche_id=4, distance_gare_km=0.5),
    dict(id=33, type="culture", nom="Tour Eiffel", commune="Paris 7e Arrondissement", departement="75", lat=48.8583, lon=2.2945, gare_proche_id=4, distance_gare_km=0.8),
]


def _h(h, m):
    return h * 3600 + m * 60


@pytest.fixture
def engine(monkeypatch):
    with tempfile.TemporaryDirectory() as dossier:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{dossier}/test.db")
        migration.migrate()
        with Session(get_engine()) as session:
            session.add_all([Lieu(**l) for l in LIEUX])
            session.add_all([Gare(lieu_id=i, code_uic=f"8700000{i}") for i in (1, 2, 3, 4)])
            session.add_all([Reseau(id="sncf", nom="SNCF", mode="train"), Reseau(id="amp", nom="Aix-Marseille-Provence", mode="bus")])
            session.add_all([Ligne(id="sncf:tgv", reseau_id="sncf", nom="TGV INOUI", type_transport="TGV"),
                             Ligne(id="amp:40", reseau_id="amp", nom="AIX - AEROPORT", type_transport="Bus")])
            session.add_all([Arret(id="sncf:2", reseau_id="sncf", lieu_id=2, nom="Aix TGV"), Arret(id="sncf:3", reseau_id="sncf", lieu_id=3, nom="Paris GdL"),
                             Arret(id="amp:20", reseau_id="amp", lieu_id=20, nom="Gare Routière"), Arret(id="amp:21", reseau_id="amp", lieu_id=21, nom="Gare TGV")])
            session.add_all([Circulation(id="sncf:6120", ligne_id="sncf:tgv", service_id="sncf:s", numero="6120"),
                             Circulation(id="amp:a", ligne_id="amp:40", service_id="amp:s", destination="Aéroport"),
                             Circulation(id="amp:b", ligne_id="amp:40", service_id="amp:s", destination="Aéroport")])
            session.add_all([Calendrier(service_id="sncf:s", date=JOUR), Calendrier(service_id="amp:s", date=JOUR)])
            session.add_all([Passage(circulation_id="sncf:6120", ordre=1, arret_id="sncf:2", heure_arrivee=_h(14, 18), heure_depart=_h(14, 18)),
                             Passage(circulation_id="sncf:6120", ordre=2, arret_id="sncf:3", heure_arrivee=_h(17, 22), heure_depart=_h(17, 22)),
                             Passage(circulation_id="amp:a", ordre=1, arret_id="amp:20", heure_arrivee=_h(13, 10), heure_depart=_h(13, 10)),
                             Passage(circulation_id="amp:a", ordre=2, arret_id="amp:21", heure_arrivee=_h(13, 30), heure_depart=_h(13, 30)),
                             Passage(circulation_id="amp:b", ordre=1, arret_id="amp:20", heure_arrivee=_h(13, 40), heure_depart=_h(13, 40)),
                             Passage(circulation_id="amp:b", ordre=2, arret_id="amp:21", heure_arrivee=_h(14, 0), heure_depart=_h(14, 0))])
            session.commit()
        yield get_engine()


def _gare(engine, i):
    return itineraire._lieu(engine, i)


def test_gare_de_ville_vise_celle_des_trains_directs(engine):
    assert acheminement.gare_de_ville(engine, 48.8566, 2.3522, [2]) == 3           # le TGV depuis Aix TGV arrive à Gare de Lyon, pas à Saint-Michel
    assert acheminement.gare_de_ville(engine, 48.8566, 2.3522, [1]) == 3           # sans train direct : la gare la plus desservie de la ville
    assert acheminement.gare_de_ville(engine, 0.0, 0.0, [1]) is None


def test_gare_relais_la_plus_proche_avec_des_trains_directs(engine, monkeypatch):
    monkeypatch.setattr(acheminement, "MIN_TRAINS_RELAIS", 1)
    assert acheminement.gare_relais(engine, _gare(engine, 1), _gare(engine, 3))["nom"] == "Aix-en-Provence TGV"
    assert acheminement.gare_relais(engine, _gare(engine, 2), _gare(engine, 3)) is None        # Aix TGV a déjà son train direct


def test_acheminer_en_car_le_premier_ou_le_dernier_qui_arrive_a_temps(engine):
    a, b = _gare(engine, 1), _gare(engine, 2)
    sections = acheminement.acheminer(engine, a, b, datetime.combine(JOUR, datetime.min.time()) + timedelta(hours=13))
    assert [s["mode"] for s in sections] == ["walking", "bus", "walking"]
    car = sections[1]
    assert car["ligne"] == "AIX - AEROPORT" and car["depart"].strftime("%H:%M") == "13:10" and car["arrivee"].strftime("%H:%M") == "13:30"
    assert car["de"] == "Gare Routière" and car["vers"] == "Gare TGV" and len(car["arrets_lonlat"]) == 2
    tard = acheminement.acheminer(engine, a, b, datetime.combine(JOUR, datetime.min.time()) + timedelta(hours=13),
                                  au_plus_tard=datetime.combine(JOUR, datetime.min.time()) + timedelta(hours=14, minutes=8))
    assert tard[1]["depart"].strftime("%H:%M") == "13:40"                           # le dernier car qui arrive avant 14:08


def test_acheminer_en_voiture_sans_car_ce_jour_la(engine):
    autre_jour = datetime.combine(JOUR + timedelta(days=3), datetime.min.time()) + timedelta(hours=13)
    (voiture,) = acheminement.acheminer(engine, _gare(engine, 1), _gare(engine, 2), autre_jour)
    assert voiture["mode"] == "car" and voiture["depart"] == autre_jour and 15 * 60 <= voiture["duree_s"] <= 30 * 60 and voiture["co2_g"] > 0


def test_assembler_ajoute_le_car_au_trajet(engine):
    avant = acheminement.acheminer(engine, _gare(engine, 1), _gare(engine, 2), datetime.combine(JOUR, datetime.min.time()) + timedelta(hours=13))
    train = {"duree_s": 3 * 3600, "correspondances": 0, "co2_g": 1500.0, "depart": avant[-1]["arrivee"] + timedelta(minutes=40),
             "arrivee": avant[-1]["arrivee"] + timedelta(hours=3, minutes=40), "sections": []}
    t = acheminement.assembler(avant, train)
    assert t["via"] and t["correspondances"] == 1 and t["depart"] == avant[0]["depart"] and t["co2_g"] > 1500
    assert t["duree_s"] == int((t["arrivee"] - t["depart"]).total_seconds())


def _trajet_api(de, vers, depart, numero="6120"):
    return {"duree_s": 3 * 3600, "correspondances": 0, "depart": depart, "arrivee": depart + timedelta(hours=3), "co2_g": 1500.0,
            "sections": [{"type": "public_transport", "mode": "train", "de_lonlat": de, "vers_lonlat": vers, "arrets_lonlat": [], "duree_s": 3 * 3600,
                          "de": "Gare", "vers": "Paris Gare de Lyon", "ligne": "TGV INOUI", "numero": numero, "depart": depart, "arrivee": depart + timedelta(hours=3),
                          "retard_min": 0}]}


def test_rechercher_une_ville_et_l_option_par_la_gare_relais(engine, monkeypatch):
    monkeypatch.setattr(acheminement, "MIN_TRAINS_RELAIS", 1)
    appels = []

    def api(a, b, quand=None, nombre=3):
        appels.append((a, b))
        heure = (quand or datetime.now()).replace(second=0, microsecond=0)
        return [_trajet_api((5.4453, 43.5229), (2.3744, 48.8443), heure + timedelta(minutes=30), "TER+TGV")] if a.endswith("01") else \
            [_trajet_api((5.3175, 43.4552), (2.3744, 48.8443), heure + timedelta(minutes=8))]
    monkeypatch.setattr(navitia, "itineraires", api)
    quand = datetime.combine(JOUR, datetime.min.time()) + timedelta(hours=13)
    r = itineraire.rechercher(1, "ville:Paris|75", quand=quand, engine=engine)
    assert r["gare_arrivee"]["nom"] == "Paris Gare de Lyon" and r["relais"]["nom"] == "Aix-en-Provence TGV"
    assert ("stop_area:SNCF:87000001", "stop_area:SNCF:87000003") in appels and ("stop_area:SNCF:87000002", "stop_area:SNCF:87000003") in appels
    via = [t for t in r["trajets"] if t.get("via")]
    assert len(via) == 1 and [s["mode"] for s in via[0]["sections"]][:3] == ["walking", "bus", "walking"]


def test_noms_des_services_et_des_gares():
    assert itineraire.libelle_section({"ligne": "TGV INOUI", "numero": "6120"}) == "TGV INOUI 6120"
    assert itineraire.libelle_section({"ligne": "RER", "numero": "FECA", "code": "D"}) == "RER D"
    assert itineraire.libelle_section({"ligne": "ZOU !", "numero": "880139"}) == "TER ZOU ! 880139"
    assert itineraire.libelle_section({"ligne": "AIX - AEROPORT", "mode_physique": "Bus", "mode": "bus"}) == "Bus AIX - AEROPORT"
    assert itineraire.nom_service({"ligne": "Intercités de nuit", "numero": "5789"}) == "Intercités de nuit"
    assert itineraire.nom_service({"ligne": "Navette", "mode_physique": "Autocar"}) == "Car"
    assert itineraire.nom_service({"mode": "car"}) == "Voiture"
    assert itineraire.nom_gare("Paris - Gare de Lyon - Hall 1 & 2 (Paris)") == "Paris Gare de Lyon Hall 1 & 2"


def test_une_destination_n_apparait_qu_une_fois(engine):
    eiffel = [o["label"] for o in itineraire.chercher_destinations("eiffel", "tous", engine) if o["type"] != "ville"]
    assert len(eiffel) == 1                                     # « Tour Eiffel », « La tour Eiffel », « Tour Eiffel (Paris 7e Arrondissement) »
