"""Vérifie lib/navitia.py avec une fausse API : aucun accès au réseau, le token ne doit jamais apparaître."""
import sys
from datetime import datetime
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib import navitia

TOKEN = "jeton-secret-1234"
PLACES = {"places": [
    {"id": "admin:fr:41018", "name": "Blois", "embedded_type": "administrative_region"},
    {"id": "stop_area:SNCF:87574004", "name": "Blois - Chambord (Blois)", "embedded_type": "stop_area",
     "stop_area": {"coord": {"lat": "47.585449", "lon": "1.323759"}}}]}
JOURNEYS = {"journeys": [{
    "duration": 11040, "nb_transfers": 0, "departure_date_time": "20261012T091000", "arrival_date_time": "20261012T121400",
    "co2_emission": {"value": 1554.1, "unit": "g CO₂e/passenger"},
    "sections": [
        {"type": "crow_fly", "mode": "walking", "duration": 0, "from": {"name": "Paris"}, "to": {"name": "Paris"}},
        {"type": "public_transport", "duration": 11040, "from": {"name": "Paris Gare de Lyon"}, "to": {"name": "Marseille Saint-Charles"},
         "display_informations": {"commercial_mode": "TGV INOUI", "headsign": "6101", "direction": "Marseille"},
         "departure_date_time": "20261012T091000", "arrival_date_time": "20261012T121400"}]}]}


class Reponse:
    def __init__(self, contenu, statut=200):
        self.contenu, self.status_code = contenu, statut

    def json(self):
        if self.contenu is None:
            raise ValueError("pas du JSON")
        return self.contenu


@pytest.fixture
def api(monkeypatch):
    """Fausse API : appels enregistrés dans `appels`, réponse à changer avec api['reponse']."""
    monkeypatch.setenv("NAVITIA_TOKEN", TOKEN)
    etat = {"appels": [], "reponse": Reponse(PLACES)}

    def get(url, params, auth, timeout):
        etat["appels"].append((url, params, auth))
        return etat["reponse"]
    monkeypatch.setattr(navitia.requests, "get", get)
    return etat


def test_id_gare():
    assert navitia.id_gare("87686006") == "stop_area:SNCF:87686006"
    assert navitia.id_gare("0087686006") == "stop_area:SNCF:87686006"


def test_chercher_gares_ne_garde_que_les_gares(api):
    gares = navitia.chercher_gares("Blois")
    assert list(gares["id"]) == ["stop_area:SNCF:87574004"] and gares.loc[0, "lat"] == pytest.approx(47.585449)
    url, params, auth = api["appels"][0]
    assert url.endswith("/coverage/sncf/places") and auth == (TOKEN, "") and TOKEN not in url and TOKEN not in str(params)


def test_itineraires(api):
    api["reponse"] = Reponse(JOURNEYS)
    trajets = navitia.itineraires("stop_area:SNCF:87686006", "stop_area:SNCF:87751008", quand="2026-10-12 08:00")
    t = trajets[0]
    assert t["duree_s"] == 11040 and t["correspondances"] == 0 and t["depart"] == datetime(2026, 10, 12, 9, 10) and t["co2_g"] == 1554.1
    assert [s["type"] for s in t["sections"]] == ["crow_fly", "public_transport"]
    assert t["sections"][1]["ligne"] == "TGV INOUI" and t["sections"][1]["mode"] == "train" and t["sections"][1]["numero"] == "6101"
    assert api["appels"][0][1]["datetime"] == "20261012T080000"


def test_aucun_trajet(api):
    api["reponse"] = Reponse({"error": {"id": "no_solution", "message": "no solution found"}}, 404)
    assert navitia.itineraires("stop_area:SNCF:1", "stop_area:SNCF:2", quand="2026-10-12 08:00") == []


def test_erreurs_sans_fuite_du_token(api, monkeypatch):
    api["reponse"] = Reponse({"error": {"message": "x"}}, 401)
    with pytest.raises(RuntimeError, match="token refusé") as e:
        navitia.chercher_gares("Blois")
    assert TOKEN not in str(e.value)

    def panne(url, params, auth, timeout):
        raise requests.ConnectionError(f"échec sur {url} avec {auth}")
    monkeypatch.setattr(navitia.requests, "get", panne)
    with pytest.raises(RuntimeError, match="injoignable") as e:
        navitia.chercher_gares("Blois")
    assert TOKEN not in str(e.value) and "ConnectionError" in str(e.value)


def test_token_absent(monkeypatch):
    monkeypatch.delenv("NAVITIA_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="NAVITIA_TOKEN"):
        navitia.chercher_gares("Blois")
