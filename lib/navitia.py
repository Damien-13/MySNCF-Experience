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
from zoneinfo import ZoneInfo

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


def _theorique(base, reel):
    """Horaire théorique en heure de Paris (datetime sans fuseau), à partir du « base_… » de l'API et de l'horaire réel.
    Sur les trains suivis en temps réel, l'API donne l'horaire de base en UTC (2 h de moins l'été) alors que l'horaire réel est local :
    si l'écart est exactement le décalage de Paris, on convertit (sinon c'est un vrai retard). None si l'API ne donne pas d'horaire de base."""
    if not base:
        return None
    base = _date(base)
    decalage = ZoneInfo("Europe/Paris").utcoffset(reel)
    return base + decalage if reel - base == decalage else base


def _lonlat(lieu):
    """(lon, lat) d'un lieu Navitia (gare, arrêt, adresse…), None s'il n'a pas de coordonnées."""
    lieu = lieu or {}
    coord = (lieu.get(lieu.get("embedded_type")) or {}).get("coord")
    return (float(coord["lon"]), float(coord["lat"])) if coord else None


def _arrets(s):
    """Positions (lon, lat) de tous les arrêts d'une section de transport public, dans l'ordre (vide si l'API ne les donne pas)."""
    out = []
    for d in s.get("stop_date_times") or []:
        coord = (d.get("stop_point") or {}).get("coord")
        if coord:
            out.append((float(coord["lon"]), float(coord["lat"])))
    return out


def _retard_min(s):
    """Retard à l'arrivée d'une section en minutes (0 si à l'heure ou sans suivi temps réel)."""
    if "arrival_date_time" not in s:
        return 0
    arrivee = _date(s["arrival_date_time"])
    theorique = _theorique(s.get("base_arrival_date_time"), arrivee)
    return max(round((arrivee - theorique).total_seconds() / 60), 0) if theorique else 0


def _section(s):
    infos = s.get("display_informations", {})
    return {
        "de_lonlat": _lonlat(s.get("from")), "vers_lonlat": _lonlat(s.get("to")), "arrets_lonlat": _arrets(s),
        "type": s["type"], "mode": s.get("mode") or ("train" if s["type"] == "public_transport" else None),
        "duree_s": s["duration"], "de": s.get("from", {}).get("name"), "vers": s.get("to", {}).get("name"),
        "ligne": infos.get("commercial_mode"), "numero": infos.get("headsign"), "direction": infos.get("direction"),
        "reseau": infos.get("network"), "mode_physique": infos.get("physical_mode"),
        "depart": _date(s["departure_date_time"]) if "departure_date_time" in s else None,
        "arrivee": _date(s["arrival_date_time"]) if "arrival_date_time" in s else None,
        "temps_reel": s.get("data_freshness") == "realtime",
        "retard_min": _retard_min(s),
    }


def itineraires(depart, arrivee, quand=None, nombre=3, temps_reel=True):
    """Trajets en train entre deux lieux : gares (id_gare) ou positions « lon;lat ». `quand` : datetime ou « AAAA-MM-JJ HH:MM »
    (maintenant par défaut). `temps_reel` : horaires avec les retards connus de l'API. Retourne une liste de trajets (vide s'il n'y en a pas) : duree_s, correspondances, depart, arrivee,
    co2_g et sections (type, mode, duree_s, de, vers, de_lonlat, vers_lonlat, arrets_lonlat, ligne, numero, direction, reseau, mode_physique, depart, arrivee,
    temps_reel, retard_min)."""
    quand = pd.Timestamp(quand).to_pydatetime() if quand is not None else datetime.now()
    statut, contenu = _get("/journeys", **{"from": depart, "to": arrivee, "datetime": quand.strftime("%Y%m%dT%H%M%S"), "count": nombre,
                                      "data_freshness": "realtime" if temps_reel else "base_schedule"})
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
