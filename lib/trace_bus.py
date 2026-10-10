"""Tracé d'un car sur la route : retrouve, parmi les lignes de bus d'OpenStreetMap (table ligne_bus), celle qui passe par les arrêts du car.

Les numéros de ligne de l'API SNCF (« 89047 ») ne sont pas ceux d'OpenStreetMap (« 400 ») : on rapproche par la position des arrêts.
Une ligne convient si elle passe à moins de RAYON_M de chaque arrêt.
Le tracé relie, deux par deux, les points de la ligne les plus proches des arrêts, par le plus court chemin sur la ligne (les morceaux d'une ligne ne sont pas
tous bout à bout dans OpenStreetMap : on les relie par leurs extrémités communes). Un tronçon qui fait un détour énorme écarte la ligne. Parmi les lignes qui conviennent, on garde celle qui colle le mieux aux arrêts, puis la plus courte.
Les calculs se font sur une projection plane (équirectangulaire à 46,5° de latitude), comme lib/reseau_ferre.py.

Usage :
    points, sur_route = trace_car([(lon, lat), …])    # points [(lon, lat), …] ; sur_route faux = aucune ligne trouvée, les arrêts reliés en ligne droite
"""
import json
import math
from functools import lru_cache

import networkx as nx
import numpy as np
import sqlalchemy as sa

from lib.db.connection import get_engine
from lib.reseau_ferre import DECIMALES, KM_PAR_DEGRE_LAT, KM_PAR_DEGRE_LON

RAYON_M = 1200            # distance maximale entre un arrêt et la ligne (un arrêt peut être à l'écart de la route, sur un parking relais)
RAPPORT_DETOUR_MAX = 4     # un tronçon de ligne plus de 4 fois plus long que la ligne droite (+ DETOUR_LIBRE_M) n'est pas le bon
DETOUR_LIBRE_M = 3000
POIDS_LONGUEUR = 0.01     # à qualité égale, la ligne la plus courte l'emporte
PAS_M = 25                # les segments de la ligne sont redécoupés tous les PAS_M pour accrocher les arrêts au plus près
MARGE_DEG = RAYON_M / (KM_PAR_DEGRE_LAT * 1000)


def _plan(point):
    return round(point[0] * KM_PAR_DEGRE_LON * 1000, 1), round(point[1] * KM_PAR_DEGRE_LAT * 1000, 1)


def _geo(x, y):
    return x / (KM_PAR_DEGRE_LON * 1000), y / (KM_PAR_DEGRE_LAT * 1000)


@lru_cache(maxsize=256)
def _graphe(geometrie):
    """(graphe, coordonnées des sommets) d'une ligne : un sommet par point (redécoupé tous les PAS_M), une arête entre points consécutifs, pondérée en mètres."""
    g = nx.Graph()
    for polyligne in json.loads(geometrie):
        points = [_plan(p) for p in polyligne]
        for a, b in zip(points, points[1:]):
            n = max(1, math.ceil(math.dist(a, b) / PAS_M))
            etapes = [(round(a[0] + (b[0] - a[0]) * k / n, 1), round(a[1] + (b[1] - a[1]) * k / n, 1)) for k in range(n + 1)]
            for p, q in zip(etapes, etapes[1:]):
                if p != q:
                    g.add_edge(p, q, weight=math.dist(p, q))
    sommets = list(g.nodes)
    return g, sommets, np.array(sommets)


def _evaluer(geometrie, arrets):
    """(score, points du tracé en mètres) si la ligne passe près de chaque arrêt, en les desservant dans l'ordre, sinon None.
    Le tracé relie les arrêts deux par deux : le plus court chemin du premier au dernier pourrait prendre un raccourci et sauter un arrêt."""
    g, sommets, tableau = _graphe(geometrie)
    if not len(sommets):
        return None
    accroches, ecarts = [], []
    for a in arrets:
        distances = np.hypot(tableau[:, 0] - a[0], tableau[:, 1] - a[1])
        i = int(distances.argmin())
        if distances[i] > RAYON_M:
            return None
        accroches.append(sommets[i])
        ecarts.append(float(distances[i]))
    chemin = [accroches[0]]
    for (de, vers), (a, b) in zip(zip(accroches, accroches[1:]), zip(arrets, arrets[1:])):
        if de == vers:
            continue
        try:
            partie = nx.shortest_path(g, de, vers, weight="weight")
        except nx.NetworkXNoPath:
            return None
        if nx.path_weight(g, partie, "weight") > RAPPORT_DETOUR_MAX * math.dist(a, b) + DETOUR_LIBRE_M:
            return None
        chemin += partie[1:]
    if len(chemin) < 2:
        return None
    return sum(ecarts) + POIDS_LONGUEUR * nx.path_weight(g, chemin, "weight"), chemin


@lru_cache(maxsize=512)
def _chercher(arrets, engine):
    """Points (lon, lat) du tracé de la meilleure ligne, ou None."""
    plan = [_plan(a) for a in arrets]
    lons, lats = [a[0] for a in arrets], [a[1] for a in arrets]
    with engine.connect() as conn:
        candidates = conn.execute(sa.text(
            "SELECT geometrie FROM ligne_bus WHERE lat_min <= :lat1 AND lat_max >= :lat2 AND lon_min <= :lon1 AND lon_max >= :lon2"),
            {"lat1": min(lats) + MARGE_DEG, "lat2": max(lats) - MARGE_DEG, "lon1": min(lons) + MARGE_DEG, "lon2": max(lons) - MARGE_DEG}).fetchall()
    meilleur = None
    for (geometrie,) in candidates:
        resultat = _evaluer(geometrie, plan)
        if resultat and (meilleur is None or resultat[0] < meilleur[0]):
            meilleur = resultat
    if meilleur is None:
        return None
    points = [_geo(x, y) for x, y in meilleur[1]]
    return tuple((round(lon, DECIMALES), round(lat, DECIMALES)) for lon, lat in [arrets[0], *points, arrets[-1]])


def trace_car(arrets, engine=None):
    """(points [(lon, lat), …], sur_route) du car qui dessert `arrets` ([(lon, lat), …] dans l'ordre). Sans ligne trouvée : les arrêts, en ligne droite."""
    arrets = tuple((float(lon), float(lat)) for lon, lat in arrets)
    if len(arrets) < 2:
        return list(arrets), False
    try:
        points = _chercher(arrets, engine or get_engine())
    except sa.exc.DatabaseError:        # table absente (base d'avant la migration 004)
        points = None
    return (list(points), True) if points else (list(arrets), False)
