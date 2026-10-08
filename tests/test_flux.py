"""Vérifie la lecture des flux temps réel (lib/flux.py) avec de faux serveurs GBFS : aucun accès au réseau."""
import sys
from pathlib import Path

import pandas as pd
import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib import flux

V3 = {  # Bordeaux, Nantes : data.feeds, noms en liste, num_vehicles_available, dates ISO
    "https://v3/gbfs.json": {"data": {"feeds": [{"name": "station_information", "url": "https://v3/info"},
                                               {"name": "station_status", "url": "https://v3/status"}]}},
    "https://v3/info": {"data": {"stations": [
        {"station_id": "1", "name": [{"text": "Meriadeck", "language": "fr"}], "lat": 44.84, "lon": -0.58, "capacity": 42},
        {"station_id": "2", "name": [{"text": "Harbour", "language": "en"}, {"text": "Port", "language": "fr"}], "lat": 44.85, "lon": -0.57, "capacity": 10}]}},
    "https://v3/status": {"data": {"stations": [
        {"station_id": "1", "num_vehicles_available": 3, "num_docks_available": 39, "is_renting": True, "last_reported": "2026-10-08T13:22:05Z"},
        {"station_id": "2", "num_vehicles_available": 0, "num_docks_available": 10, "is_renting": False, "last_reported": "2026-10-08T13:00:00Z"}]}},
}
V2 = {  # Rennes, Strasbourg : data.fr.feeds, nom simple, num_bikes_available, dates epoch, drapeaux 0/1
    "https://v2/gbfs.json": {"data": {"fr": {"feeds": [{"name": "station_information", "url": "https://v2/info"},
                                                      {"name": "station_status", "url": "https://v2/status"}]}}},
    "https://v2/info": {"data": {"stations": [{"station_id": 5501, "name": "République", "lat": 48.11, "lon": -1.68, "capacity": 45}]}},
    "https://v2/status": {"data": {"stations": [{"station_id": "5501", "num_bikes_available": 7, "num_docks_available": 38, "is_renting": 1, "last_reported": 1791465668}]}},
}


class Reponse:
    def __init__(self, contenu, statut=200):
        self.contenu, self.statut = contenu, statut

    def raise_for_status(self):
        if self.statut >= 400:
            raise requests.HTTPError(f"{self.statut}")

    def json(self):
        if self.contenu is None:
            raise ValueError("pas du JSON")
        return self.contenu


@pytest.fixture
def faux_reseau(monkeypatch):
    """Les URL de V3 et V2 répondent ; ce que le test ajoute à `pages` aussi ; le reste est une erreur 404."""
    pages = {**V3, **V2}
    monkeypatch.setattr(flux.requests, "get", lambda url, timeout: Reponse(pages[url]) if url in pages else Reponse(None, 404))
    for cle in [k for k in __import__("os").environ if k.startswith("FLUX_")]:
        monkeypatch.delenv(cle)
    monkeypatch.setenv("FLUX_VLS_BORDEAUX_URL", "https://v3/gbfs.json?apiKey=secret")
    pages["https://v3/gbfs.json?apiKey=secret"] = V3["https://v3/gbfs.json"]
    monkeypatch.setenv("FLUX_VLS_RENNES_URL", "https://v2/gbfs.json")
    return pages


def test_noms(faux_reseau):
    assert flux.noms() == ["vls_bordeaux", "vls_rennes"]


def test_lire_gbfs_v3(faux_reseau):
    df = flux.lire("vls_bordeaux")
    assert list(df.columns) == flux.COLONNES
    assert list(df["nom"]) == ["Meriadeck", "Port"]                     # le nom français est préféré
    assert list(df["velos_disponibles"]) == [3, 0] and list(df["places_disponibles"]) == [39, 10]
    assert list(df["en_service"]) == [True, False]
    assert df.loc[0, "mis_a_jour"] == pd.Timestamp("2026-10-08 13:22:05", tz="UTC")


def test_lire_gbfs_v2(faux_reseau):
    df = flux.lire("vls_rennes")
    assert df.loc[0, "nom"] == "République" and df.loc[0, "station_id"] == "5501"   # identifiant numérique → texte, jointure OK
    assert df.loc[0, "velos_disponibles"] == 7 and df.loc[0, "en_service"]
    assert df.loc[0, "mis_a_jour"] == pd.Timestamp(1791465668, unit="s", tz="UTC")


def test_date_impossible_devient_inconnue():
    dates = flux._date([0, "0001-01-01T00:00:00Z", None, 1791465668, "n'importe quoi", 1791465668000])
    assert list(dates.isna()) == [True, True, True, False, True, False]
    assert dates[3] == dates[5]                                          # secondes et millisecondes donnent la même date


def test_flux_inconnu(faux_reseau):
    with pytest.raises(KeyError):
        flux.lire("vls_inconnu")


def test_flux_en_panne_ne_bloque_pas_les_autres(faux_reseau, monkeypatch):
    monkeypatch.setenv("FLUX_VLS_PANNE_URL", "https://panne/gbfs.json?apiKey=secret")
    stations, erreurs = flux.lire_tous()
    assert set(stations["flux"]) == {"vls_bordeaux", "vls_rennes"} and len(stations) == 3
    assert list(erreurs) == ["vls_panne"] and "secret" not in erreurs["vls_panne"]   # la clé d'accès ne fuit pas dans le message


def test_tous_les_flux_en_panne(faux_reseau, monkeypatch):
    monkeypatch.setattr(flux.requests, "get", lambda url, timeout: Reponse(None, 500))
    stations, erreurs = flux.lire_tous()
    assert stations.empty and list(stations.columns) == flux.COLONNES and len(erreurs) == 2
