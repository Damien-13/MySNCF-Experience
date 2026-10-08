"""Transformation des trains internationaux qui desservent la France (Eurostar, Renfe AVE, Trenitalia France) vers reseau, ligne,
circulation, calendrier, arret et passage. Outils communs : gtfs.py.

Usage : python src/transformation/trains_europeens.py   (les gares doivent déjà être chargées : voir transformation.py)
Relançable sans risque : chaque réseau est remplacé en entier (tout passe ou rien).

Rattachement des arrêts aux gares de la base :
- Eurostar : son stop_code est le code UIC sans la clé de contrôle (7 chiffres au lieu de 8) ;
- Renfe et Trenitalia : pas de code UIC, la gare la plus proche à moins de RAYON_GARE_M mètres.
Chevauchement avec le GTFS SNCF mesuré : 0 % pour Eurostar et Renfe ; 16 circulations Trenitalia sur 1 612 (1 %) ont le même trajet,
la même heure et le même jour qu'un train du GTFS SNCF, trop peu et trop incertain pour justifier un rapprochement : aucune règle appliquée.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import sqlalchemy as sa

import gtfs
from lib.db.connection import get_engine
from lib.db.models import Gare
from lieux import lire_gares

RAYON_GARE_M = 300
# source (dossier de data/) → réseau, type de toutes ses lignes, et rattachement aux gares par code UIC à 7 chiffres ou par position
RESEAUX = {
    "eurostar": {"reseau": {"id": "eurostar", "nom": "Eurostar", "mode": "train"}, "type": "Eurostar", "par_uic": True},
    "renfe_ave": {"reseau": {"id": "renfe_ave", "nom": "Renfe AVE", "mode": "train"}, "type": "AVE", "par_uic": False},
    "trenitalia_france": {"reseau": {"id": "trenitalia", "nom": "Trenitalia France", "mode": "train"}, "type": "Trenitalia", "par_uic": False},
}


def codes_uic(arrets, codes_gares):
    """{stop_id: code UIC à 8 chiffres} pour les arrêts dont le stop_code (7 chiffres) est le début du code d'une gare connue."""
    par_prefixe = {code[:7]: code for code in codes_gares}
    return {stop_id: par_prefixe[code] for stop_id, code in zip(arrets["stop_id"], arrets["stop_code"]) if code in par_prefixe}


def nettoyer(brut, reseau, type_ligne, par_uic, codes_gares=()):
    uic = codes_uic(brut["stops"], codes_gares) if par_uic else None
    types = dict.fromkeys(brut["routes"]["route_id"], type_ligne)
    return gtfs.normaliser(brut, reseau["id"], uic=uic, types_lignes=types)


def codes_gares_en_base(engine=None):
    with (engine or get_engine()).connect() as conn:
        return [code for (code,) in conn.execute(sa.select(Gare.code_uic)) if code]


def transformer():
    if lire_gares().empty:
        sys.exit("Aucune gare en base : lancer d'abord l'étape gares (python src/transformation/transformation.py)")
    codes = codes_gares_en_base()
    total = []
    for dossier, config in RESEAUX.items():
        frames = nettoyer(gtfs.lire(ROOT / "data" / dossier), config["reseau"], config["type"], config["par_uic"], codes)
        lignes, circulations, arrets, passages = gtfs.charger(frames, config["reseau"], dossier, rayon_gare_m=None if config["par_uic"] else RAYON_GARE_M)
        print(f"{config['reseau']['nom']} : {lignes} lignes, {circulations} circulations, {arrets} arrêts, {passages} passages, "
              f"{len(frames['calendrier'])} jours de circulation")
        total.append((lignes, circulations, arrets, passages))
    return total


if __name__ == "__main__":
    transformer()
