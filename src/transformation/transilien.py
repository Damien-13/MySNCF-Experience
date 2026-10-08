"""Transformation des horaires théoriques des RER et Transilien (GTFS d'Île-de-France Mobilités) vers reseau, ligne, circulation,
calendrier, arret et passage. Outils communs : gtfs.py.

Usage : python src/transformation/transilien.py   (les gares doivent déjà être chargées : voir transformation.py)
Relançable sans risque : le réseau « transilien » est remplacé en entier (tout passe ou rien).

Règle de gestion : ce fichier contient aussi des lignes TER de cinq régions. Elles sont écartées, car le GTFS SNCF (sncf.py) est la source
des TER : 40 % de ces circulations s'y trouvaient déjà (même gare de départ, même gare d'arrivée, même heure), aucune des lignes RER ou
Transilien n'y est. Gardés : les RER, les Transilien et leurs cars de remplacement (travaux).
Les arrêts n'ont pas de code UIC : ils sont rattachés à la gare de la base la plus proche si elle est à moins de RAYON_GARE_M mètres.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gtfs
from lieux import lire_gares

SOURCE = "transilien"
DOSSIER = ROOT / "data" / "transilien"
RESEAU = {"id": "transilien", "nom": "RER et Transilien (Île-de-France Mobilités)", "mode": "train"}
RAYON_GARE_M = 300
AGENCES = {"RER": "RER", "Transilien": "Transilien"}      # nom d'agence du fichier → type de ligne ; l'agence « TER » est écartée


def nettoyer(brut):
    agences = brut["agency"].set_index("agency_id")["agency_name"]
    routes = brut["routes"].assign(agence=brut["routes"]["agency_id"].map(agences))
    brut = gtfs.garder_lignes({**brut, "routes": routes}, routes["agence"].isin(AGENCES))
    routes = brut["routes"]
    types = routes["agence"].map(AGENCES).where(routes["route_type"] != "3", "Car de remplacement")
    brut["routes"] = routes.assign(route_long_name=routes["route_long_name"].where(
        routes["route_type"] == "3", routes["agence"] + " " + routes["route_short_name"]))        # « RER A » plutôt que « A »
    return gtfs.normaliser(brut, RESEAU["id"], types_lignes=dict(zip(routes["route_id"], types)))


def lire():
    import pandas as pd
    brut = gtfs.lire(DOSSIER)
    brut["agency"] = pd.read_csv(DOSSIER / "agency.txt", dtype=str)
    return brut


def transformer():
    if lire_gares().empty:
        sys.exit("Aucune gare en base : lancer d'abord l'étape gares (python src/transformation/transformation.py)")
    frames = nettoyer(lire())
    lignes, circulations, arrets, passages = gtfs.charger(frames, RESEAU, SOURCE, rayon_gare_m=RAYON_GARE_M)
    print(f"Transilien : {lignes} lignes, {circulations} circulations, {arrets} arrêts, {passages} passages, "
          f"{len(frames['calendrier'])} jours de circulation")
    return lignes, circulations, arrets, passages


if __name__ == "__main__":
    transformer()
