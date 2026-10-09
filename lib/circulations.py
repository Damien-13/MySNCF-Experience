"""Trains en circulation sur tout le réseau à un instant donné, d'après les horaires théoriques de la base. Sans dépendance à Dash.

Un train est entre deux arrêts consécutifs de sa circulation : on connaît son départ, son arrivée et le tracé entre les deux (table trace_trajet).
Pas de retards ici : l'API SNCF ne les donne que pour un trajet cherché (voir lib/navitia.py), pas pour tout le réseau.

Usage :
    trains = en_cours(datetime.now(), engine=engine)    # liste de dicts pour le navigateur (src/assets/trains.js), vide si la base n'a pas les tracés
Au premier appel, charge en mémoire les horaires des trains (environ 1 million de segments, quelques secondes) ; les appels suivants sont rapides.
"""
import json
from datetime import datetime, timedelta

import pandas as pd
import sqlalchemy as sa

from lib.db.connection import get_engine
from lib.itineraire import style_ligne
from lib import sprites
from lib.reseau_ferre import TYPES_HORS_RAIL

MAX_POINTS = 12                 # points gardés par tracé : le dashboard n'affiche que des repères pour tout le réseau
FENETRE_S = 900                 # on envoie les trains qui roulent maintenant et ceux qui partent dans les 15 prochaines minutes
MARGE_S = 60

_cache = {}


def _decimer(points, maximum=MAX_POINTS):
    """Au plus `maximum` points d'un tracé [[lat, lon], …], en gardant le premier et le dernier."""
    if len(points) <= maximum:
        return points
    pas = (len(points) - 1) / (maximum - 1)
    return [points[round(i * pas)] for i in range(maximum)]


def charger(engine=None):
    """Horaires des trains (DataFrame, un segment par ligne), tracés entre arrêts et noms d'arrêts, gardés en mémoire pour les appels suivants."""
    engine = engine or get_engine()
    cle = str(engine.url)
    if cle in _cache:
        return _cache[cle]
    segments = pd.read_sql(sa.text(
        "SELECT c.id AS circulation, c.service_id, p1.arret_id AS a, p2.arret_id AS b, "
        "COALESCE(p1.heure_depart, p1.heure_arrivee) AS t0, COALESCE(p2.heure_arrivee, p2.heure_depart) AS t1, l.type_transport, c.numero "
        "FROM ligne l JOIN circulation c ON c.ligne_id = l.id JOIN passage p1 ON p1.circulation_id = c.id "
        "JOIN passage p2 ON p2.circulation_id = p1.circulation_id AND p2.ordre = p1.ordre + 1 "
        "WHERE l.reseau_id IN (SELECT id FROM reseau WHERE mode = 'train') AND (l.type_transport IS NULL OR l.type_transport NOT IN :types)"
    ).bindparams(sa.bindparam("types", expanding=True)), engine, params={"types": list(TYPES_HORS_RAIL)}).dropna(subset=["t0", "t1"])
    segments[["t0", "t1"]] = segments[["t0", "t1"]].astype("int64")
    styles = {t: style_ligne({"ligne": t}) for t in segments["type_transport"].dropna().unique()}
    inconnu = style_ligne({})
    segments["style"] = segments["type_transport"].map(styles).where(segments["type_transport"].notna(), None)
    segments["style"] = segments["style"].apply(lambda s: s if isinstance(s, dict) else inconnu)
    with engine.connect() as conn:
        traces = {(a, b): (json.loads(g), bool(v)) for a, b, g, v in conn.execute(sa.text("SELECT arret_depart_id, arret_arrivee_id, geometrie, sur_voie FROM trace_trajet"))}
        noms = dict(conn.execute(sa.text("SELECT id, nom FROM arret")).all())
    _cache[cle] = {"segments": segments, "traces": traces, "noms": noms}
    return _cache[cle]


def _services(engine, jour):
    with engine.connect() as conn:
        return {s for (s,) in conn.execute(sa.text("SELECT service_id FROM calendrier WHERE date = :d"), {"d": jour.isoformat()})}


def en_cours(maintenant=None, engine=None, fenetre_s=FENETRE_S):
    """Trains qui roulent à `maintenant` ou partent dans `fenetre_s` secondes : un dict par segment, avec id (la circulation, pour garder le même repère
    d'un arrêt au suivant), libelle, style, sprite / longueur_m / rapport (l'image du train et sa taille réelle, voir lib/sprites.py), de, vers, points [[lat, lon], …],
    t0, t1 (secondes depuis l'époque), retard_min (0), marche (faux)."""
    engine = engine or get_engine()
    maintenant = maintenant or datetime.now()
    donnees = charger(engine)
    if not donnees["traces"]:
        return []
    minuit = datetime(maintenant.year, maintenant.month, maintenant.day)
    trains, apparences = [], {}
    # Les horaires après minuit (au-delà de 86400 s) appartiennent au service de la veille : on regarde aujourd'hui et hier.
    for decalage in (0, 1):
        debut_jour = minuit - timedelta(days=decalage)
        actifs = _services(engine, debut_jour.date())
        s = donnees["segments"]
        depuis_minuit = (maintenant - debut_jour).total_seconds()
        choisis = s[s["service_id"].isin(actifs) & (s["t0"] <= depuis_minuit + fenetre_s) & (s["t1"] >= depuis_minuit - MARGE_S)]
        for ligne in choisis.itertuples():
            trace = donnees["traces"].get((ligne.a, ligne.b))
            if trace is None:
                continue
            numero = f" {ligne.numero}" if ligne.numero else ""
            libelle = f"{ligne.type_transport or 'Train'}{numero}"
            apparence = apparences.setdefault((ligne.style["cle"], ligne.type_transport or ""), sprites.infos(ligne.style["cle"], ligne.type_transport or ""))
            trains.append({
                **apparence, "id": ligne.circulation, "libelle": libelle, "style": ligne.style,
                "de": donnees["noms"].get(ligne.a), "vers": donnees["noms"].get(ligne.b),
                "points": [[round(lat, 4), round(lon, 4)] for lon, lat in _decimer(trace[0])],        # trace_trajet stocke [lon, lat]
                "t0": debut_jour.timestamp() + ligne.t0, "t1": debut_jour.timestamp() + ligne.t1, "retard_min": 0, "marche": False,
            })
    return trains
