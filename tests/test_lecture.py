"""Vérifie les résumés écrits de la page (lib/lecture.py), lus par les lecteurs d'écran et par le bouton « Écouter »."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import lecture

TRAIN = {"type": "public_transport", "mode": "train", "ligne": "ZOU !", "numero": "880121", "de": "Aix-en-Provence", "vers": "Veynes",
         "depart": "2026-10-12 08:53:00", "arrivee": "2026-10-12 09:37:00", "duree_s": 2640, "retard_min": 0}
CAR = {"type": "public_transport", "mode": "train", "ligne": "REGIONAURA", "numero": "409710", "de": "Veynes", "vers": "Grenoble",
       "depart": "2026-10-12 12:13:00", "arrivee": "2026-10-12 14:30:00", "duree_s": 8220, "retard_min": 5}
MARCHE = {"type": "street_network", "mode": "walking", "duree_s": 180}
COURTE_MARCHE = {"type": "transfer", "mode": "walking", "duree_s": 30}
TRAJETS = [{"depart": "2026-10-12 08:53:00", "arrivee": "2026-10-12 14:01:00", "duree_s": 18480, "correspondances": 3, "co2_g": 2600, "sections": [TRAIN, MARCHE, COURTE_MARCHE, CAR]},
           {"depart": "2026-10-12 09:53:00", "arrivee": "2026-10-12 15:27:00", "duree_s": 20040, "correspondances": 0, "co2_g": None, "sections": [TRAIN]}]
R = {"depart": {"nom": "Aix-en-Provence"}, "destination": {"nom": "Tomorrowland Winter"}, "gare_arrivee": {"nom": "Lancey"}, "distance_km": 22.14,
     "dernier_km": ["Voiture / Taxi", "plus de 5 km de la gare"], "faisable": False, "trajets": TRAJETS, "trajets_retour": [], "erreur_api": None,
     "meme_gare": False, "periode_invalide": None}


def test_duree_et_heure_parlees():
    assert lecture.duree_parlee(18480) == "5 heures 8 minutes"
    assert lecture.duree_parlee(3600) == "1 heure"
    assert lecture.duree_parlee(2700) == "45 minutes"
    assert lecture.duree_parlee(60) == "1 minute"
    assert lecture.heure_parlee("2026-10-12 08:53:00") == "8 heures 53"
    assert lecture.heure_parlee("2026-10-12 14:00:00") == "14 heures"


def test_resume_de_l_option_choisie():
    texte = lecture.resume_itineraire(R, {"sens": "aller", "index": 0})
    assert "Aller de Aix-en-Provence à Lancey" in texte
    assert "Option 1 sur 2" in texte and "départ à 8 heures 53, arrivée à 14 heures 1" in texte
    assert "durée 5 heures 8 minutes" in texte and "3 correspondances" in texte
    assert "ZOU ! 880121, de Aix-en-Provence à Veynes, départ à 8 heures 53, arrivée à 9 heures 37" in texte
    assert "avec 5 minutes de retard" in texte and "à pied, 3 minutes" in texte
    assert texte.count("à pied") == 1 and "secondes" not in texte      # la marche de moins d'une minute n'est pas dite
    assert "2,6 kilos de CO2" in texte
    assert "22,1 kilomètres" in texte and "voiture / taxi" in texte and "difficile" in texte


def test_les_noms_de_gare_perdent_leur_commune_entre_parentheses():
    assert lecture.nom_parle("Marseille Saint-Charles (Marseille)") == "Marseille Saint-Charles"
    assert lecture.nom_parle("Lancey") == "Lancey"
    section = {**TRAIN, "de": "Aix-en-Provence (Aix-en-Provence)", "vers": "Veynes Dévoluy (Veynes)"}
    assert "de Aix-en-Provence à Veynes Dévoluy," in lecture.resume_trajet({**TRAJETS[1], "sections": [section]}, 1, 1)


def test_changer_d_option_change_le_resume():
    texte = lecture.resume_itineraire(R, {"sens": "aller", "index": 1})
    assert "Option 2 sur 2" in texte and "trajet direct" in texte and "CO2" not in texte


def test_resume_du_retour_inverse_les_gares():
    r = {**R, "trajets_retour": [TRAJETS[1]]}
    assert "Retour de Lancey à Aix-en-Provence" in lecture.resume_itineraire(r, {"sens": "retour", "index": 0})


@pytest.mark.parametrize("modif, attendu", [
    ({"trajets": [], "erreur_api": "API SNCF injoignable"}, "horaires sont indisponibles"),
    ({"trajets": [], "gare_arrivee": None}, "Aucune gare d'arrivée connue"),
    ({"trajets": [], "meme_gare": True}, "aucun train à prendre"),
    ({"trajets": [], "periode_invalide": "Date passée"}, "Date passée"),
    ({"trajets": []}, "Aucun train trouvé"),
])
def test_resume_sans_trajet(modif, attendu):
    assert attendu in lecture.resume_itineraire({**R, **modif})


def test_resume_sans_recherche_ou_avec_message():
    assert lecture.resume_itineraire(None) == lecture.PHRASE_ACCUEIL
    assert lecture.resume_itineraire({"message": "Lieu introuvable en base.", "niveau": "danger"}) == "Lieu introuvable en base."


def test_resume_de_l_analyse():
    texte = lecture.resume_analyse("87,8 %", "278 207", "12,2 %")
    assert "87,8 %" in texte and "278 207" in texte and "12,2 %" in texte and "15 kilomètres" in texte
    brut = lecture.resume_analyse("87.8 %", "278 207", "12.2 %")                        # les indicateurs affichés ont un point décimal : la voix dit « virgule »
    assert "87,8 %" in brut and "12,2 %" in brut and "87.8" not in brut
