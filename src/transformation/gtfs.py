"""Transformation d'un GTFS (horaires théoriques d'un réseau) vers les tables reseau, ligne, circulation, calendrier, arret, passage.

Outils communs à tous les réseaux ; chaque réseau a son module (sncf.py…) qui dit où est son GTFS et comment reconnaître ses gares.
Identifiants préfixés par le réseau (« sncf:… ») pour rester uniques entre réseaux. Heures de passage en secondes depuis minuit
(plus de 86400 pour les trains de nuit).

Rattachement des arrêts : un arrêt dont le code UIC est celui d'une gare de la base pointe vers cette gare (arret.lieu_id). Les autres
reçoivent leur propre lieu (type « arret_bus » pour un car, « arret_train » sinon), avec leur gare la plus proche si elle est à moins de DISTANCE_GARE_MAX_KM (donc pas pour les arrêts à l'étranger).
Seuls les arrêts physiques (location_type 0) sont gardés ; les zones d'arrêt (location_type 1) ne servent qu'au regroupement.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import sqlalchemy as sa

from lib.db.connection import get_engine
from lib.db.models import Arret, Calendrier, Circulation, Gare, Ligne, Lieu, Passage, Reseau
from lieux import inserer, lignes_lieu, lire_gares, rattacher_aux_gares

DISTANCE_GARE_MAX_KM = 50          # au-delà, un arrêt n'a pas de gare « proche » (arrêts à l'étranger)
FICHIERS = ["routes", "trips", "stop_times", "stops", "calendar_dates"]


def lire(dossier):
    """Les fichiers du GTFS en texte (les identifiants gardent leurs zéros). Retourne {nom: DataFrame}."""
    return {nom: pd.read_csv(Path(dossier) / f"{nom}.txt", dtype=str) for nom in FICHIERS}


def en_secondes(heures):
    """« 07:02:00 » → 25320 ; « 25:10:00 » (train de nuit) → 90600 ; vide ou illisible → NaN."""
    parts = heures.str.extract(r"^\s*(\d{1,3}):(\d{2}):(\d{2})\s*$").astype(float)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def normaliser(brut, reseau_id, uic=None, libelles=None):
    """Nettoie un GTFS. `uic` : Series code UIC par stop_id (None si l'arrêt n'est pas une gare connue) ;
    `libelles` : Series libellé par stop_id (« Train TER », « Car TER »…), qui donne aussi le type de chaque ligne.
    Retourne {lignes, circulations, calendrier, arrets, passages} ; arrets a lat, lon, uic et lieu_type en plus des colonnes de la table."""
    p = f"{reseau_id}:"
    stops = brut["stops"][brut["stops"]["location_type"].fillna("0") == "0"].copy()
    stops["uic"] = stops["stop_id"].map(uic) if uic is not None else None
    stops["libelle"] = stops["stop_id"].map(libelles) if libelles is not None else None

    trips = brut["trips"]
    type_ligne = None
    if libelles is not None:
        vus = brut["stop_times"][["trip_id", "stop_id"]].merge(trips[["trip_id", "route_id"]], on="trip_id")
        vus["libelle"] = vus["stop_id"].map(libelles)
        type_ligne = vus.dropna(subset=["libelle"]).groupby("route_id")["libelle"].agg(lambda s: s.mode().iloc[0])
    routes = brut["routes"]
    lignes = pd.DataFrame({
        "id": p + routes["route_id"], "reseau_id": reseau_id, "nom": routes["route_long_name"].fillna(routes["route_short_name"]),
        "type_transport": routes["route_id"].map(type_ligne) if type_ligne is not None else None,
        "couleur": ("#" + routes["route_color"]).where(routes["route_color"].notna()),
    })
    circulations = pd.DataFrame({
        "id": p + trips["trip_id"], "ligne_id": p + trips["route_id"], "service_id": p + trips["service_id"],
        "numero": trips["block_id"], "destination": trips["trip_headsign"],
    })
    dates = brut["calendar_dates"]
    ajouts = dates[dates["exception_type"] == "1"]       # le GTFS ne liste que des jours de circulation ajoutés
    calendrier = pd.DataFrame({"service_id": p + ajouts["service_id"], "date": pd.to_datetime(ajouts["date"], format="%Y%m%d").dt.date}).drop_duplicates()
    st = brut["stop_times"]
    passages = pd.DataFrame({
        "circulation_id": p + st["trip_id"], "ordre": st["stop_sequence"].astype(int), "arret_id": p + st["stop_id"],
        "heure_arrivee": en_secondes(st["arrival_time"]), "heure_depart": en_secondes(st["departure_time"]),
    })
    arrets = pd.DataFrame({
        "id": p + stops["stop_id"], "reseau_id": reseau_id, "nom": stops["stop_name"],
        "lat": pd.to_numeric(stops["stop_lat"], errors="coerce"), "lon": pd.to_numeric(stops["stop_lon"], errors="coerce"),
        "uic": stops["uic"], "libelle": stops["libelle"],
    })
    arrets = arrets[arrets["id"].isin(set(passages["arret_id"]))].reset_index(drop=True)      # seuls les arrêts desservis
    passages = passages[passages["arret_id"].isin(set(arrets["id"]))]
    return {"lignes": lignes, "circulations": circulations, "calendrier": calendrier, "arrets": arrets, "passages": passages}


def _entiers(df, colonnes):
    """Dicts prêts à insérer, avec les colonnes entières en int Python et NaN → None."""
    out = df.astype(object).where(df.notna(), None)
    for c in colonnes:
        out[c] = out[c].map(lambda v: None if v is None else int(v))
    return out.to_dict("records")


def charger(frames, reseau, source, engine=None):
    """Remplace en une transaction tout le réseau : reseau (dict id, nom, mode), lignes, circulations, calendrier, arrêts, passages
    et les lieux d'arrêts créés pour lui. Retourne le nombre de lignes, circulations, arrêts et passages chargés."""
    engine = engine or get_engine()
    rid = reseau["id"]
    gares = lire_gares(engine)
    arrets = frames["arrets"].copy()
    with engine.begin() as conn:
        lieux_arrets = sa.select(Lieu.id).where(Lieu.type.in_(["arret_bus", "arret_train"]), Lieu.source == source)
        circulations = sa.select(Circulation.id).join(Ligne, Ligne.id == Circulation.ligne_id).where(Ligne.reseau_id == rid)
        conn.execute(sa.delete(Passage).where(Passage.circulation_id.in_(circulations)))
        conn.execute(sa.delete(Calendrier).where(Calendrier.service_id.like(f"{rid}:%")))
        conn.execute(sa.delete(Circulation).where(Circulation.id.in_(circulations)))
        conn.execute(sa.delete(Arret).where(Arret.reseau_id == rid))
        conn.execute(sa.delete(Lieu).where(Lieu.id.in_(lieux_arrets)))
        conn.execute(sa.delete(Ligne).where(Ligne.reseau_id == rid))
        conn.execute(sa.delete(Reseau).where(Reseau.id == rid))

        gare_par_uic = dict(conn.execute(sa.select(Gare.code_uic, Gare.lieu_id)).all())
        arrets["lieu_id"] = arrets["uic"].map(gare_par_uic)
        nouveaux = arrets[arrets["lieu_id"].isna() & arrets["lat"].notna() & arrets["lon"].notna()].copy()
        nouveaux["type"] = nouveaux["libelle"].fillna("").str.startswith("Car").map({True: "arret_bus", False: "arret_train"})
        premier = (conn.scalar(sa.select(sa.func.max(Lieu.id))) or 0) + 1
        nouveaux["lieu_id"] = range(premier, premier + len(nouveaux))
        lieux = rattacher_aux_gares(nouveaux[["nom", "lat", "lon"]], gares).assign(id=nouveaux["lieu_id"].to_numpy())
        trop_loin = lieux["distance_gare_km"].isna() | (lieux["distance_gare_km"] > DISTANCE_GARE_MAX_KM)
        lieux.loc[trop_loin, ["gare_proche_id", "distance_gare_km"]] = None
        lignes_lieux = lignes_lieu(lieux, None, source)
        for ligne, type_ in zip(lignes_lieux, nouveaux["type"]):
            ligne["type"] = type_
        arrets.loc[nouveaux.index, "lieu_id"] = nouveaux["lieu_id"]

        conn.execute(sa.insert(Reseau), [{**reseau, "source": source}])
        inserer(conn, Lieu, lignes_lieux)
        inserer(conn, Ligne, _entiers(frames["lignes"], []))
        inserer(conn, Arret, _entiers(arrets[["id", "reseau_id", "lieu_id", "nom"]], ["lieu_id"]))
        inserer(conn, Circulation, _entiers(frames["circulations"], []))
        inserer(conn, Calendrier, _entiers(frames["calendrier"], []))
        inserer(conn, Passage, _entiers(frames["passages"], ["ordre", "heure_arrivee", "heure_depart"]))
    return len(frames["lignes"]), len(frames["circulations"]), len(arrets), len(frames["passages"])
