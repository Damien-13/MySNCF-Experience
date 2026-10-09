"""Transformation complète : lance chaque étape dans l'ordre (nettoyage, transformation et chargement d'un domaine à la fois).

Usage : python src/transformation/transformation.py
Chaque étape est un module de src/transformation/ avec une fonction transformer(). L'ordre compte :
les gares d'abord, car les autres lieux s'y rattachent (gare_proche_id). Relançable sans risque.
Pour ajouter un domaine : créer son module, puis l'ajouter à ETAPES.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bus
import culture
import evenement
import festival
import gare
import sncf
import tourisme
import trace_trajets
import trains_europeens
import transilien
import velo
import voies

ETAPES = [
    ("gares", gare),
    ("sncf", sncf),
    ("transilien", transilien),
    ("trains européens", trains_europeens),
    ("culture", culture),
    ("tourisme", tourisme),
    ("evenements", evenement),
    ("festivals", festival),
    ("velo", velo),
    ("bus", bus),
    ("tracé ferroviaire", voies),
    ("tracé des trajets", trace_trajets),
]


def transformer():
    """Lance toutes les étapes. S'arrête à la première qui échoue (les précédentes restent chargées)."""
    for nom, module in ETAPES:
        print(f"── {nom} ──")
        module.transformer()


if __name__ == "__main__":
    transformer()
