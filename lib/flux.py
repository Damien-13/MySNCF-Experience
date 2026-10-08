"""Flux temps réel (FLUX_<NOM>_URL du .env) : lit les stations de vélos en libre-service, au format GBFS (v2 et v3).

À appeler depuis le dashboard à chaque actualisation : rien n'est stocké en base ni sur disque.

Usage :
    from lib.flux import noms, lire, lire_tous
    noms()                           # ['vls_bordeaux_tbm', 'vls_nantes_naolib', …]
    lire("vls_nantes_naolib")        # DataFrame : une ligne par station
    stations, erreurs = lire_tous()  # tous les flux ; un flux en panne n'empêche pas les autres

Colonnes : flux, station_id, nom, lat, lon, capacite, velos_disponibles, places_disponibles, en_service, mis_a_jour (UTC).
"""
import os

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

DELAI_SECONDES = 20
COLONNES = ["flux", "station_id", "nom", "lat", "lon", "capacite", "velos_disponibles", "places_disponibles", "en_service", "mis_a_jour"]


def noms():
    """Noms courts des flux déclarés dans le .env (« vls_nantes_naolib » pour FLUX_VLS_NANTES_NAOLIB_URL)."""
    return sorted(k[len("FLUX_"):-len("_URL")].lower() for k in os.environ if k.startswith("FLUX_") and k.endswith("_URL"))


def _json(url):
    """Contenu JSON d'une URL. L'URL peut contenir une clé d'accès : elle n'apparaît jamais dans les erreurs."""
    try:
        reponse = requests.get(url, timeout=DELAI_SECONDES)
        reponse.raise_for_status()
        return reponse.json()
    except requests.RequestException as erreur:
        raise RuntimeError(f"flux injoignable ({type(erreur).__name__})") from None
    except ValueError:
        raise RuntimeError("flux illisible (JSON invalide)") from None


def _adresses(annuaire):
    """{nom du fichier GBFS: URL} depuis gbfs.json : v3 = data.feeds, v2 = data.<langue>.feeds (fr de préférence)."""
    data = annuaire["data"]
    if "feeds" not in data:
        data = data.get("fr") or next(iter(data.values()))
    return {f["name"]: f["url"] for f in data["feeds"]}


def _texte(valeur):
    """Nom d'une station : texte simple (v2) ou liste [{text, language}] (v3, français de préférence)."""
    if isinstance(valeur, list):
        choix = next((v for v in valeur if v.get("language") == "fr"), valeur[0] if valeur else {})
        return choix.get("text")
    return valeur


def _stations(adresses, fichier):
    if fichier not in adresses:
        raise RuntimeError(f"fichier {fichier} absent de l'annuaire du flux")
    stations = pd.DataFrame(_json(adresses[fichier])["data"]["stations"])
    stations["station_id"] = stations["station_id"].astype(str)         # nombre dans un fichier, texte dans l'autre selon les flux
    return stations


def _colonne(df, *candidates):
    """Première colonne présente parmi `candidates` (vide si aucune) : GBFS v2 et v3 ne nomment pas tout pareil."""
    return next((df[c] for c in candidates if c in df.columns), pd.Series([None] * len(df), index=df.index))


def _date(valeur):
    """Epoch (secondes ou millisecondes) ou texte ISO → date UTC. Une valeur impossible (0, an 1…) devient NaT."""
    texte = pd.Series(valeur)
    nombres = pd.to_numeric(texte, errors="coerce")
    nombres = nombres.where(nombres.between(1e9, 1e13))              # avant 2001 ou après l'an 318 000 : donnée fausse
    nombres = nombres.where(nombres < 1e11, nombres / 1000)          # millisecondes → secondes
    depuis_nombre = pd.to_datetime(nombres, unit="s", utc=True, errors="coerce")
    depuis_texte = pd.to_datetime(texte.where(nombres.isna() & ~pd.to_numeric(texte, errors="coerce").notna()), utc=True, errors="coerce")
    return depuis_nombre.fillna(depuis_texte)


def lire(nom):
    """Stations d'un flux (voir noms()) avec leur disponibilité du moment. Lève RuntimeError si le flux est injoignable."""
    cle = f"FLUX_{nom.upper()}_URL"
    if cle not in os.environ:
        raise KeyError(f"flux inconnu : {nom} (attendu : {cle} dans le .env)")
    adresses = _adresses(_json(os.environ[cle]))
    infos, statuts = _stations(adresses, "station_information"), _stations(adresses, "station_status")
    stations = infos.merge(statuts, on="station_id", how="left", suffixes=("", "_statut"))
    en_service = _colonne(stations, "is_renting").map(lambda v: None if v is None or pd.isna(v) else bool(v))
    return pd.DataFrame({
        "flux": nom,
        "station_id": stations["station_id"],
        "nom": _colonne(stations, "name").map(_texte),
        "lat": pd.to_numeric(_colonne(stations, "lat")),
        "lon": pd.to_numeric(_colonne(stations, "lon")),
        "capacite": pd.to_numeric(_colonne(stations, "capacity")),
        "velos_disponibles": pd.to_numeric(_colonne(stations, "num_vehicles_available", "num_bikes_available")),
        "places_disponibles": pd.to_numeric(_colonne(stations, "num_docks_available")),
        "en_service": en_service,
        "mis_a_jour": _date(_colonne(stations, "last_reported")),
    }, columns=COLONNES)


def lire_tous():
    """Tous les flux. Retourne (stations, erreurs) : un DataFrame et {flux: message} pour ceux qui ont échoué."""
    morceaux, erreurs = [], {}
    for nom in noms():
        try:
            morceaux.append(lire(nom))
        except RuntimeError as erreur:
            erreurs[nom] = str(erreur)
    return (pd.concat(morceaux, ignore_index=True) if morceaux else pd.DataFrame(columns=COLONNES)), erreurs
