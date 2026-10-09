"""Réseau des voies ferrées (table troncon_voie) et plus court chemin entre deux positions.

Utilisé par le calcul des tracés (src/transformation/trace_trajets.py) et par le dashboard (lib/itineraire.py).
Les distances sont calculées sur une projection plane (équirectangulaire à 46,5° de latitude) : suffisant pour la France continentale.

Usage :
    reseau = charger_reseau()                                  # une fois (lit troncon_voie), None si la table est vide
    points, sur_voie = chemin(reseau, (lon, lat), (lon, lat))  # points [[lon, lat], …] ; sur_voie faux = ligne droite
"""
import json
import math

import numpy as np
import sqlalchemy as sa
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from lib.db.connection import get_engine
from lib.db.models import TronconVoie

DECIMALES = 5
TYPES_HORS_RAIL = ("Car TER", "Car à réservation", "Car de remplacement", "Navette")      # lignes des réseaux de train qui roulent sur la route
RAYON_JONCTION_KM = 0.5
RAYON_ACCROCHAGE_KM = 1.0
RAPPORT_MAX = 3.0
MARGE_RECHERCHE_KM = 2.0
KM_PAR_DEGRE_LAT = 110.57
KM_PAR_DEGRE_LON = 111.32 * math.cos(math.radians(46.5))


def longueur_km(points):
    """Longueur d'une polyligne [(lon, lat), …] en kilomètres (haversine)."""
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(points, points[1:]):
        p1, p2 = math.radians(lat1), math.radians(lat2)
        a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
        total += 2 * 6371.0088 * math.asin(math.sqrt(a))
    return total


def en_km(lonlat):
    lonlat = np.asarray(lonlat, dtype=float)
    return np.column_stack([lonlat[:, 0] * KM_PAR_DEGRE_LON, lonlat[:, 1] * KM_PAR_DEGRE_LAT])


def construire_reseau(geometries):
    """Réseau des voies depuis des polylignes [[lon, lat], …] : (points lon/lat, arbre des points en km, graphe creux des distances en km).
    Chaque point est un nœud relié au suivant. Les tronçons ne partagent pas de nœuds : les deux extrémités de chaque tronçon
    sont reliées aux points d'autres tronçons à moins de RAYON_JONCTION_KM (les trous du tracé sont aux extrémités)."""
    points, aretes, troncon = [], [], []
    for numero, ligne in enumerate(geometries):
        debut = len(points)
        points.extend(ligne)
        troncon.extend([numero] * len(ligne))
        aretes.extend((debut + k - 1, debut + k) for k in range(1, len(ligne)))
    points = np.array(points, dtype=float)
    xy, troncon = en_km(points), np.array(troncon)
    arbre = cKDTree(xy)
    bouts = np.flatnonzero((np.r_[True, troncon[1:] != troncon[:-1]]) | (np.r_[troncon[1:] != troncon[:-1], True]))
    for a, voisins in zip(bouts, arbre.query_ball_point(xy[bouts], RAYON_JONCTION_KM)):
        aretes.extend((a, b) for b in voisins if troncon[a] != troncon[b])
    aretes = np.array(aretes)
    poids = np.linalg.norm(xy[aretes[:, 0]] - xy[aretes[:, 1]], axis=1)
    n = len(points)
    graphe = coo_matrix((np.r_[poids, poids], (np.r_[aretes[:, 0], aretes[:, 1]], np.r_[aretes[:, 1], aretes[:, 0]])), shape=(n, n)).tocsr()
    return points, arbre, graphe


def charger_reseau(engine=None):
    """Réseau construit depuis troncon_voie, ou None si la table est vide."""
    with (engine or get_engine()).connect() as conn:
        geometries = [json.loads(g) for g in conn.scalars(sa.select(TronconVoie.geometrie))]
    return construire_reseau(geometries) if geometries else None


def geometrie(points):
    """Points arrondis [[lon, lat], …], sans doublon consécutif."""
    out = []
    for lon, lat in points:
        p = [round(float(lon), DECIMALES), round(float(lat), DECIMALES)]
        if not out or out[-1] != p:
            out.append(p)
    return out


def suivre(points, dist, pred, source, fin, depart, arrivee, ligne_droite_km):
    """Chemin [[lon, lat], …] de `depart` à `arrivee` à partir d'un Dijkstra (dist, pred) lancé depuis le nœud `source`,
    ou None s'il n'y a pas de chemin fiable : inatteignable, ou plus long que RAPPORT_MAX fois la ligne droite (mauvaise voie)."""
    if not np.isfinite(dist[fin]) or dist[fin] > RAPPORT_MAX * max(ligne_droite_km, 1.0):
        return None
    noeuds = [fin]
    while noeuds[-1] != source:
        noeuds.append(int(pred[noeuds[-1]]))
    return geometrie([depart, *points[noeuds[::-1]], arrivee])


def chemin(reseau, depart, arrivee):
    """Plus court chemin sur les voies entre deux positions (lon, lat) : (points [[lon, lat], …], sur_voie).
    Ligne droite (sur_voie faux) si le réseau est absent, si une position est à plus de RAYON_ACCROCHAGE_KM des voies ou sans chemin fiable."""
    droite = geometrie([depart, arrivee])
    if reseau is None:
        return droite, False
    points, arbre, graphe = reseau
    xy = en_km([depart, arrivee])
    distance, noeud = arbre.query(xy)
    if distance.max() > RAYON_ACCROCHAGE_KM:
        return droite, False
    ligne_droite = float(np.linalg.norm(xy[0] - xy[1]))
    source, fin = int(noeud[0]), int(noeud[1])
    dist, pred = dijkstra(graphe, indices=source, limit=ligne_droite * RAPPORT_MAX + MARGE_RECHERCHE_KM, return_predecessors=True)
    trouve = suivre(points, dist, pred, source, fin, depart, arrivee, ligne_droite)
    return (trouve, True) if trouve else (droite, False)
