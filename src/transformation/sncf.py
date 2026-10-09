"""Transformation des horaires théoriques SNCF (GTFS : TGV, TER, Intercités, Ouigo, cars TER…) vers reseau, ligne, circulation,
calendrier, arret et passage. Outils communs : gtfs.py.

Usage : python src/transformation/sncf.py   (les gares doivent déjà être chargées : voir transformation.py)
Relançable sans risque : le réseau « sncf » est remplacé en entier (tout passe ou rien).

Un stop_id SNCF ressemble à « StopPoint:OCETrain TER-87574004 » : le libellé (« Train TER », « Car TER », « TGV INOUI »…) donne le type
de la ligne, et les 8 chiffres sont le code UIC de la gare. Un car TER, ou un arrêt hors de la liste des gares, devient un lieu à part.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gtfs
from lieux import lire_gares

SOURCE = "horaires_sncf_gtfs"
DOSSIER = ROOT / "data" / "horaires_sncf_gtfs"
RESEAU = {"id": "sncf", "nom": "SNCF", "mode": "train"}


def uic_et_libelle(stop_ids):
    """(code UIC, libellé) par stop_id, depuis « StopPoint:OCE<libellé>-<UIC à 8 chiffres> »."""
    morceaux = stop_ids.str.extract(r"^StopPoint:OCE(?P<libelle>.*)-(?P<uic>\d{8})$")
    morceaux.index = stop_ids
    return morceaux["uic"], morceaux["libelle"]


def nettoyer(brut):
    uic, libelle = uic_et_libelle(brut["stops"]["stop_id"])
    return gtfs.normaliser(brut, RESEAU["id"], uic=uic.dropna().to_dict(), libelles=libelle.dropna().to_dict())


def transformer():
    if lire_gares().empty:
        sys.exit("Aucune gare en base : lancer d'abord l'étape gares (python src/transformation/transformation.py)")
    frames = nettoyer(gtfs.lire(DOSSIER))
    lignes, circulations, arrets, passages = gtfs.charger(frames, RESEAU, SOURCE)
    print(f"SNCF : {lignes} lignes, {circulations} circulations, {arrets} arrêts, {passages} passages, "
          f"{len(frames['calendrier'])} jours de circulation")
    return lignes, circulations, arrets, passages


if __name__ == "__main__":
    transformer()
