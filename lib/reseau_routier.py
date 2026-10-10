"""Réseau routier (table troncon_route) et trajet d'un car arrêt par arrêt, comme un GPS.

Utilisé par lib/trace_bus.py quand la ligne OpenStreetMap d'un car manque ou est incomplète.
Les routes de la zone des arrêts sont chargées en un graphe orienté (sens uniques respectés), pondéré par le temps de parcours (vitesse selon le type de route) ;
chaque arrêt est accroché au point de route le plus proche, puis on relie les arrêts deux par deux par le plus court chemin. Rien n'interdit le demi-tour à un arrêt.
Les distances sont calculées sur une projection plane (équirectangulaire à 46,5° de latitude), comme lib/reseau_ferre.py.

Usage :
    points, complet = chemin_par_arrets([(lon, lat), …])     # points [(lon, lat), …] ; complet faux = au moins un tronçon est resté en ligne droite
"""
import json
import math

import numpy as np
import sqlalchemy as sa
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree

from lib.db.connection import get_engine
from lib.reseau_ferre import DECIMALES, KM_PAR_DEGRE_LAT, KM_PAR_DEGRE_LON

TAILLE_TUILE_DEG = 0.1
VITESSES_KMH = {"motorway": 100, "motorway_link": 50, "trunk": 80, "trunk_link": 50, "primary": 70, "primary_link": 40, "secondary": 60, "secondary_link": 40,
                "tertiary": 50, "tertiary_link": 40, "unclassified": 40, "busway": 50}
VITESSE_PAR_DEFAUT_KMH = 40
RAYON_ACCROCHAGE_M = 1500        # distance maximale entre un arrêt et la route la plus proche
MARGES_DEG = (0.15, 0.4)         # marge autour des arrêts pour charger les routes ; plus large si un arrêt reste introuvable
RAPPORT_DETOUR_MAX = 4           # un tronçon plus de 4 fois plus long que la ligne droite (+ DETOUR_LIBRE_M) n'est pas crédible : on le laisse en ligne droite
DETOUR_LIBRE_M = 5000
TAILLE_RESEAU_MIN = 1000         # un arrêt s'accroche à un morceau de réseau d'au moins ce nombre de sommets (pas à une impasse isolée)
VOISINS_ACCROCHAGE = 40
ECHELLE = 100_000


def tuile(lon, lat):
    """Numéro du carré de 0,1° qui contient la position."""
    return (math.floor(lat / TAILLE_TUILE_DEG) + 1000) * 10_000 + math.floor(lon / TAILLE_TUILE_DEG) + 1000


def _tuiles(lon_min, lat_min, lon_max, lat_max):
    return [tuile(lon, lat) for lat in np.arange(math.floor(lat_min / TAILLE_TUILE_DEG), math.floor(lat_max / TAILLE_TUILE_DEG) + 1) * TAILLE_TUILE_DEG
            for lon in np.arange(math.floor(lon_min / TAILLE_TUILE_DEG), math.floor(lon_max / TAILLE_TUILE_DEG) + 1) * TAILLE_TUILE_DEG]


def _plan(lon, lat):
    return lon * KM_PAR_DEGRE_LON * 1000, lat * KM_PAR_DEGRE_LAT * 1000


def charger_zone(engine, lon_min, lat_min, lon_max, lat_max):
    """Graphe des routes de la zone : (matrice creuse des temps de parcours en secondes, positions (lon, lat) des sommets), ou None s'il n'y a aucune route."""
    cles = ",".join(str(int(t)) for t in _tuiles(lon_min, lat_min, lon_max, lat_max))
    with engine.connect() as conn:
        lignes = conn.execute(sa.text(f"SELECT classe, sens, geometrie FROM troncon_route WHERE tuile IN ({cles})")).fetchall()
    if not lignes:
        return None
    de, vers, temps = [], [], []
    for classe, sens, geometrie in lignes:
        points = np.rint(np.array(json.loads(geometrie)) * ECHELLE).astype(np.int64)
        x, y = points[:, 0] / ECHELLE * KM_PAR_DEGRE_LON * 1000, points[:, 1] / ECHELLE * KM_PAR_DEGRE_LAT * 1000
        secondes = np.hypot(np.diff(x), np.diff(y)) / (VITESSES_KMH.get(classe, VITESSE_PAR_DEFAUT_KMH) / 3.6)
        cle = (points[:, 0] + 18_000_000) * 100_000_000 + (points[:, 1] + 9_000_000)
        de.append(cle[:-1]); vers.append(cle[1:]); temps.append(secondes)
        if sens == 0:
            de.append(cle[1:]); vers.append(cle[:-1]); temps.append(secondes)
    de, vers, temps = np.concatenate(de), np.concatenate(vers), np.concatenate(temps)
    cles_uniques, inverse = np.unique(np.concatenate([de, vers]), return_inverse=True)
    n = len(de)
    graphe = coo_matrix((temps, (inverse[:n], inverse[n:])), shape=(len(cles_uniques),) * 2).tocsr()
    lon = ((cles_uniques // 100_000_000) - 18_000_000) / ECHELLE
    lat = ((cles_uniques % 100_000_000) - 9_000_000) / ECHELLE
    return graphe, np.column_stack([lon, lat])


def _longueur_m(points):
    return sum(math.dist(_plan(*a), _plan(*b)) for a, b in zip(points, points[1:]))


def chemin_dans_zone(zone, arrets):
    """(points, complet) du trajet entre les arrêts dans le graphe `zone` (charger_zone), ou None si un arrêt est à plus de RAYON_ACCROCHAGE_M d'une route."""
    graphe, sommets = zone
    arbre = cKDTree(np.array([_plan(lon, lat) for lon, lat in sommets]))
    _, composante = connected_components(graphe, directed=True, connection="strong")      # morceaux du réseau où l'on peut aller et revenir
    tailles = np.bincount(composante)
    taille_min = min(TAILLE_RESEAU_MIN, tailles.max())
    accroches = []
    for arret in arrets:
        distances, voisins = arbre.query(_plan(*arret), k=min(VOISINS_ACCROCHAGE, len(sommets)))
        voisins = np.atleast_1d(voisins)
        distances = np.atleast_1d(distances)
        bons = [(d, v) for d, v in zip(distances, voisins) if tailles[composante[v]] >= taille_min and d <= RAYON_ACCROCHAGE_M]
        if not bons:
            return None
        accroches.append(int(bons[0][1]))
    points, complet = [], True
    for (de, vers), (a, b) in zip(zip(accroches, accroches[1:]), zip(arrets, arrets[1:])):
        partie = None
        if de != vers:
            temps, precedents = dijkstra(graphe, directed=True, indices=int(de), return_predecessors=True)
            if np.isfinite(temps[vers]):
                suite, i = [], int(vers)
                while i != de and i >= 0:
                    suite.append(i)
                    i = int(precedents[i])
                suite.append(int(de))
                trace = [tuple(sommets[i]) for i in reversed(suite)]
                if _longueur_m(trace) <= RAPPORT_DETOUR_MAX * math.dist(_plan(*a), _plan(*b)) + DETOUR_LIBRE_M:
                    partie = trace
        else:
            partie = [tuple(sommets[de])]
        if partie is None:                                  # pas de chemin crédible : ce tronçon reste en ligne droite
            partie, complet = [a, b], False
        points += partie[1:] if points and points[-1] == partie[0] else partie
    return points, complet


def chemin_par_arrets(arrets, engine=None):
    """(points [(lon, lat), …], complet) du car qui dessert `arrets` ([(lon, lat), …] dans l'ordre) sur les routes, ou None si le réseau routier ne couvre pas les arrêts."""
    engine = engine or get_engine()
    lons, lats = [a[0] for a in arrets], [a[1] for a in arrets]
    for marge in MARGES_DEG:
        zone = charger_zone(engine, min(lons) - marge, min(lats) - marge, max(lons) + marge, max(lats) + marge)
        resultat = chemin_dans_zone(zone, arrets) if zone else None
        if resultat:
            points, complet = resultat
            sortie = []
            for p in [tuple(arrets[0]), *[(round(lon, DECIMALES), round(lat, DECIMALES)) for lon, lat in points], tuple(arrets[-1])]:
                if not sortie or p != sortie[-1]:
                    sortie.append(p)
            return sortie, complet
    return None
