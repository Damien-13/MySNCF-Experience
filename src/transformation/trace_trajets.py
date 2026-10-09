"""Tracé des trains entre deux arrêts : calcule, sur le réseau de troncon_voie, le chemin de chaque paire d'arrêts consécutifs, puis remplit trace_trajet.

Usage : python src/transformation/trace_trajets.py   (le tracé des voies et les trains doivent déjà être chargés : voir transformation.py)
Relançable sans risque : trace_trajet est remplacée en entier (tout passe ou rien).

Méthode :
- Réseau : chaque point d'un tronçon est un nœud, relié au suivant. Les tronçons ne partagent pas de nœuds : les deux extrémités de chaque tronçon
  sont reliées aux points d'autres tronçons à moins de RAYON_JONCTION_KM (les trous du tracé sont aux extrémités).
- Arrêts : chacun est accroché au nœud le plus proche, s'il est à moins de RAYON_ACCROCHAGE_KM. Le tracé part de la position de l'arrêt et y revient.
- Paires : deux arrêts qui se suivent dans une circulation de train (cars, navettes et bateaux exclus), plus court chemin (Dijkstra).
- Repli en ligne droite (sur_voie faux) : arrêt trop loin du réseau (gares étrangères : Eurostar, Renfe, Trenitalia), aucun chemin,
  ou chemin plus long que RAPPORT_MAX fois la ligne droite (accrochage sur la mauvaise voie).
Les distances sont calculées sur une projection plane (équirectangulaire à 46,5° de latitude) : suffisant pour la France continentale.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import sqlalchemy as sa
from scipy.sparse.csgraph import dijkstra

from lib.db.connection import get_engine
from lib.db.models import TraceTrajet, TronconVoie
from lib.reseau_ferre import (RAPPORT_MAX, RAYON_ACCROCHAGE_KM, RAYON_JONCTION_KM, MARGE_RECHERCHE_KM,  # noqa: F401 (réexportés)
                              construire_reseau, en_km, geometrie, longueur_km, suivre)

TYPES_HORS_RAIL = ("Car TER", "Car à réservation", "Car de remplacement", "Navette")
CHUNK_SIZE = 5_000


def tracer(points, arbre, graphe, arrets, paires):
    """Une ligne par paire : arret_depart_id, arret_arrivee_id, geometrie (JSON), longueur_km, sur_voie.
    `arrets` : DataFrame indexé par id d'arrêt avec lon et lat ; `paires` : DataFrame depart, arrivee."""
    lonlat = arrets[["lon", "lat"]].to_numpy()
    distance, noeud = arbre.query(en_km(lonlat))
    position = {a: k for k, a in enumerate(arrets.index)}
    xy = en_km(lonlat)

    def droite(a, b):
        ligne = geometrie([lonlat[position[a]], lonlat[position[b]]])
        return {"arret_depart_id": a, "arret_arrivee_id": b, "geometrie": json.dumps(ligne, separators=(",", ":")),
                "longueur_km": round(longueur_km(ligne), 3), "sur_voie": False}

    resultat = []
    for source, groupe in paires.groupby(paires["depart"].map(lambda a: noeud[position[a]])):
        accrochees = [distance[position[a]] <= RAYON_ACCROCHAGE_KM and distance[position[b]] <= RAYON_ACCROCHAGE_KM
                      for a, b in zip(groupe["depart"], groupe["arrivee"])]
        a_chercher = [(a, b) for (a, b), ok in zip(zip(groupe["depart"], groupe["arrivee"]), accrochees) if ok]
        resultat.extend(droite(a, b) for (a, b), ok in zip(zip(groupe["depart"], groupe["arrivee"]), accrochees) if not ok)
        if not a_chercher:
            continue
        droites = [np.linalg.norm(xy[position[a]] - xy[position[b]]) for a, b in a_chercher]
        dist, pred = dijkstra(graphe, indices=int(source), limit=max(droites) * RAPPORT_MAX + MARGE_RECHERCHE_KM, return_predecessors=True)
        for (a, b), ligne_droite in zip(a_chercher, droites):
            fin = int(noeud[position[b]])
            ligne = suivre(points, dist, pred, source, fin, lonlat[position[a]], lonlat[position[b]], ligne_droite)
            if ligne is None:
                resultat.append(droite(a, b))
                continue
            resultat.append({"arret_depart_id": a, "arret_arrivee_id": b, "geometrie": json.dumps(ligne, separators=(",", ":")),
                             "longueur_km": round(longueur_km(ligne), 3), "sur_voie": True})
    return resultat


def lire_paires(engine):
    """(arrêts des réseaux de train avec position, paires d'arrêts consécutifs dans une circulation de train)."""
    arrets = pd.read_sql(sa.text(
        "SELECT a.id, lieu.lon, lieu.lat FROM arret a JOIN lieu ON lieu.id = a.lieu_id JOIN reseau r ON r.id = a.reseau_id "
        "WHERE r.mode = 'train' AND lieu.lon IS NOT NULL AND lieu.lat IS NOT NULL"), engine).set_index("id")
    # On part des lignes de train (index sur reseau_id) : partir de passage obligerait SQLite à parcourir toute la table (des dizaines de millions de lignes).
    paires = pd.read_sql(sa.text(
        "SELECT DISTINCT p1.arret_id AS depart, p2.arret_id AS arrivee FROM ligne l JOIN circulation c ON c.ligne_id = l.id "
        "JOIN passage p1 ON p1.circulation_id = c.id JOIN passage p2 ON p2.circulation_id = p1.circulation_id AND p2.ordre = p1.ordre + 1 "
        "WHERE l.reseau_id IN (SELECT id FROM reseau WHERE mode = 'train') AND (l.type_transport IS NULL OR l.type_transport NOT IN :types)").bindparams(
        sa.bindparam("types", expanding=True)), engine, params={"types": list(TYPES_HORS_RAIL)})
    return arrets, paires[paires["depart"].isin(arrets.index) & paires["arrivee"].isin(arrets.index)].reset_index(drop=True)


def charger(traces, engine=None):
    """Remplace en une transaction tous les tracés. Retourne le nombre de tracés chargés."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(sa.delete(TraceTrajet))
        for i in range(0, len(traces), CHUNK_SIZE):
            conn.execute(sa.insert(TraceTrajet), traces[i:i + CHUNK_SIZE])
    return len(traces)


def transformer():
    """Construit le réseau depuis troncon_voie, trace chaque paire d'arrêts, charge, et affiche la part tracée sur les voies."""
    engine = get_engine()
    with engine.connect() as conn:
        geometries = [json.loads(g) for g in conn.scalars(sa.select(TronconVoie.geometrie))]
    if not geometries:
        sys.exit("Aucun tracé en base : lancer d'abord l'étape tracé ferroviaire (python src/transformation/voies.py)")
    arrets, paires = lire_paires(engine)
    points, arbre, graphe = construire_reseau(geometries)
    traces = tracer(points, arbre, graphe, arrets, paires)
    nb = charger(traces, engine)
    sur_voie = sum(t["sur_voie"] for t in traces)
    print(f"Tracés : {nb} trajets entre arrêts, {sur_voie} sur les voies, {nb - sur_voie} en ligne droite (gare hors réseau, sans chemin ou détour)")
    return nb


if __name__ == "__main__":
    transformer()
