"""API SNCF (Navitia, couverture « sncf ») : recherche de gares et calcul d'itinéraires en train.

Le token est NAVITIA_TOKEN dans le .env ; il n'est jamais affiché ni mis dans une adresse ou un message d'erreur.
À appeler depuis le dashboard : rien n'est stocké. Documentation : https://doc.navitia.io/ (la couverture ne va que ~30 jours en avant).

Usage :
    from lib.navitia import chercher_gares, id_gare, itineraires
    chercher_gares("Blois")                                    # DataFrame : id, nom, lat, lon
    itineraires(id_gare("87686006"), id_gare("87751008"), quand="2026-10-12 08:00")   # liste de trajets
Les gares de la base (gare.code_uic) se convertissent avec id_gare(code_uic).
"""
import os
from datetime import datetime

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

URL = "https://api.navitia.io/v1/coverage/sncf"
DELAI_SECONDES = 30


def id_gare(code_uic):
    """Identifiant Navitia d'une gare à partir de son code UIC à 8 chiffres (gare.code_uic)."""
    return f"stop_area:SNCF:{str(code_uic).strip()[-8:]}"


def _get(chemin, **parametres):
    """Appelle l'API et retourne (statut, JSON). Lève RuntimeError sans jamais citer le token."""
    token = os.environ.get("NAVITIA_TOKEN")
    if not token:
        raise RuntimeError("NAVITIA_TOKEN absent du .env")
    try:
        reponse = requests.get(f"{URL}{chemin}", params=parametres, auth=(token, ""), timeout=DELAI_SECONDES)
        contenu = reponse.json()
    except requests.RequestException as erreur:
        raise RuntimeError(f"API SNCF injoignable ({type(erreur).__name__})") from None
    except ValueError:
        raise RuntimeError("API SNCF : réponse illisible") from None
    if reponse.status_code in (401, 403):
        raise RuntimeError("API SNCF : token refusé")
    return reponse.status_code, contenu


def chercher_gares(texte, nombre=5):
    """Gares dont le nom ressemble à `texte` : DataFrame id, nom, lat, lon (vide si aucune)."""
    statut, contenu = _get("/places", q=texte, type=["stop_area"], count=nombre)
    if statut >= 400:
        raise RuntimeError(f"API SNCF : {contenu.get('error', {}).get('message', statut)}")
    gares = [p for p in contenu.get("places", []) if p.get("embedded_type") == "stop_area"]
    return pd.DataFrame({
        "id": [p["id"] for p in gares], "nom": [p["name"] for p in gares],
        "lat": [float(p["stop_area"]["coord"]["lat"]) for p in gares],
        "lon": [float(p["stop_area"]["coord"]["lon"]) for p in gares],
    }, columns=["id", "nom", "lat", "lon"])


def _date(texte):
    return datetime.strptime(texte, "%Y%m%dT%H%M%S")


def _lonlat(lieu):
    """(lon, lat) d'un lieu Navitia (gare, arrêt, adresse…), None s'il n'a pas de coordonnées."""
    lieu = lieu or {}
    coord = (lieu.get(lieu.get("embedded_type")) or {}).get("coord")
    return (float(coord["lon"]), float(coord["lat"])) if coord else None


def _section(s):
    infos = s.get("display_informations", {})
    return {
        "de_lonlat": _lonlat(s.get("from")), "vers_lonlat": _lonlat(s.get("to")),
        "type": s["type"], "mode": s.get("mode") or ("train" if s["type"] == "public_transport" else None),
        "duree_s": s["duration"], "de": s.get("from", {}).get("name"), "vers": s.get("to", {}).get("name"),
        "ligne": infos.get("commercial_mode"), "numero": infos.get("headsign"), "direction": infos.get("direction"),
        "depart": _date(s["departure_date_time"]) if "departure_date_time" in s else None,
        "arrivee": _date(s["arrival_date_time"]) if "arrival_date_time" in s else None,
    }


def itineraires(depart, arrivee, quand=None, nombre=3):
    """Trajets en train entre deux lieux : gares (id_gare) ou positions « lon;lat ». `quand` : datetime ou « AAAA-MM-JJ HH:MM »
    (maintenant par défaut). Retourne une liste de trajets (vide s'il n'y en a pas) : duree_s, correspondances, depart, arrivee,
    co2_g et sections (type, mode, duree_s, de, vers, de_lonlat, vers_lonlat, ligne, numero, direction, depart, arrivee)."""
    quand = pd.Timestamp(quand).to_pydatetime() if quand is not None else datetime.now()
    statut, contenu = _get("/journeys", **{"from": depart, "to": arrivee, "datetime": quand.strftime("%Y%m%dT%H%M%S"), "count": nombre})
    if statut == 404 and contenu.get("error", {}).get("id") in ("no_origin", "no_destination", "no_solution"):
        return []
    if statut >= 400:
        raise RuntimeError(f"API SNCF : {contenu.get('error', {}).get('message', statut)}")
    return [{
        "duree_s": j["duration"], "correspondances": j["nb_transfers"],
        "depart": _date(j["departure_date_time"]), "arrivee": _date(j["arrival_date_time"]),
        "co2_g": (j.get("co2_emission") or {}).get("value"),
        "sections": [_section(s) for s in j["sections"]],
    } for j in contenu.get("journeys", [])]
