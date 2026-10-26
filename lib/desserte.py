"""Gares joignables en train depuis une gare de départ, d'après les horaires de la base : filtre « Départ » de l'onglet Analyse. Sans dépendance à Dash.

Règle de gestion : une gare est joignable si un train (ou un car TER) des réseaux de train s'y arrête après être passé à la gare de départ, directement
ou avec au plus CORRESPONDANCES_MAX correspondances (changement de train dans une gare où les deux s'arrêtent). Les horaires ne sont pas
comparés : on vérifie que le trajet existe, pas qu'il tient dans une journée. La gare de départ est toujours joignable (on y est déjà).

Usage :
    gares = joignables(engine, depart=1234)      # ensemble des id de lieu (gares et arrêts) joignables depuis la gare 1234
Au premier appel, charge en mémoire la suite des arrêts de chaque train (environ 30 secondes) ; les appels suivants sont immédiats.
"""
import threading

import pandas as pd
import sqlalchemy as sa

from lib.db.connection import get_engine

CORRESPONDANCES_MAX = 1

_cache = {}
_verrou = threading.Lock()


def construire(suites):
    """{lieu : lieux desservis après lui par un même train}. `suites` : suites d'id de lieu, une par train, dans l'ordre de passage."""
    direct = {}
    for suite in set(map(tuple, suites)):
        for i, lieu in enumerate(suite[:-1]):
            direct.setdefault(lieu, set()).update(suite[i + 1:])
    return direct


def atteintes(direct, depart, correspondances_max=CORRESPONDANCES_MAX):
    """Lieux joignables depuis `depart` avec au plus correspondances_max correspondances, départ compris."""
    gares = {depart} | direct.get(depart, set())
    for _ in range(correspondances_max):
        gares = gares.union(*(direct.get(g, ()) for g in gares))
    return gares


def charger(engine=None):
    """Index des dessertes directes, gardé en mémoire pour les appels suivants (un seul chargement à la fois)."""
    engine = engine or get_engine()
    cle = str(engine.url)
    with _verrou:
        if cle not in _cache:
            # On part des lignes de train (index sur reseau_id) : partir de passage obligerait SQLite à parcourir toute la table.
            df = pd.read_sql(sa.text(
                "SELECT p.circulation_id, p.ordre, a.lieu_id FROM ligne l JOIN circulation c ON c.ligne_id = l.id "
                "JOIN passage p ON p.circulation_id = c.id JOIN arret a ON a.id = p.arret_id "
                "WHERE l.reseau_id IN (SELECT id FROM reseau WHERE mode = 'train') AND a.lieu_id IS NOT NULL"), engine)
            suites = df.sort_values(["circulation_id", "ordre"]).groupby("circulation_id")["lieu_id"].agg(tuple)
            _cache[cle] = construire(suites)
    return _cache[cle]


def joignables(engine, depart, correspondances_max=CORRESPONDANCES_MAX):
    """Id des lieux (gares et arrêts) joignables en train depuis la gare `depart` (id de lieu)."""
    return atteintes(charger(engine), int(depart), correspondances_max)
