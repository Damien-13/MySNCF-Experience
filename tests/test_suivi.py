"""Vérifie la position des trains selon l'heure (lib/suivi.py) et leurs images (lib/sprites.py)."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib import sprites, suivi

STYLE = {"cle": "inoui", "libelle": "TGV INOUI", "couleur": "#9b0f5e", "tirets": None}
# Un train de 8 h 00 à 9 h 00 sur une voie qui va vers l'est, puis une correspondance à pied, puis un car de 9 h 30 à 10 h 00.
TRAIN = {"points": [[48.0, 2.0], [48.0, 2.3]], "depart": "2026-10-12 08:00:00", "arrivee": "2026-10-12 09:00:00", "libelle": "TGV INOUI 6101",
         "style": STYLE, "marche": False, "retard_min": 0}
MARCHE = {"points": [[48.0, 2.3], [48.001, 2.3]], "depart": "2026-10-12 09:00:00", "arrivee": "2026-10-12 09:05:00", "libelle": "À pied", "style": STYLE, "marche": True}
CAR = {"points": [[48.001, 2.3], [48.1, 2.3]], "depart": "2026-10-12 09:30:00", "arrivee": "2026-10-12 10:00:00", "libelle": "TER 12",
       "style": {**STYLE, "cle": "bus"}, "marche": False, "retard_min": 4}
HEURE = datetime(2026, 10, 12, 8, 0)


def test_point_a_le_long_du_trace_avec_son_cap():
    est = [[48.0, 2.0], [48.0, 2.2]]
    assert suivi.point_a(est, 0)[:2] == pytest.approx((48.0, 2.0))
    lat, lon, cap = suivi.point_a(est, 0.5)
    assert (lat, lon) == pytest.approx((48.0, 2.1), abs=1e-3) and cap == pytest.approx(90, abs=0.5)
    assert suivi.point_a(est, 1.5)[:2] == pytest.approx((48.0, 2.2))                                   # au-delà de l'arrivée : reste à l'arrivée
    nord = suivi.point_a([[48.0, 2.0], [48.1, 2.0], [48.1, 2.1]], 0.1)
    assert nord[2] == pytest.approx(0, abs=0.5)                                                         # le premier tronçon va vers le nord


def test_suivre_place_le_train_selon_le_temps_ecoule():
    etat = suivi.suivre([TRAIN, MARCHE, CAR], HEURE + timedelta(minutes=30))
    assert len(etat["trains"]) == 1
    train = etat["trains"][0]
    assert train["avancement"] == pytest.approx(0.5) and train["lon"] == pytest.approx(2.15, abs=1e-3) and train["cap"] == pytest.approx(90, abs=0.5)
    assert "50 %" in etat["message"] and "à l'heure" in etat["message"]


def test_un_retard_decale_l_arrivee_et_ralentit_le_train():
    en_retard = {**TRAIN, "arrivee": "2026-10-12 09:30:00", "retard_min": 30}                          # l'API annonce 30 min de retard : l'arrivée est repoussée
    retarde = suivi.suivre([en_retard], HEURE + timedelta(minutes=30))
    assert retarde["trains"][0]["avancement"] == pytest.approx(1 / 3, abs=0.005)                        # 30 min sur 90 au lieu de 30 sur 60
    assert "retard de 30 min" in retarde["message"]


def test_suivre_avant_pendant_la_correspondance_et_apres():
    avant = suivi.suivre([TRAIN, CAR], HEURE - timedelta(days=2, hours=1))
    assert avant["trains"] == [] and "part le 12/10 à 08:00" in avant["message"] and "dans 2 j" in avant["message"]
    entre = suivi.suivre([TRAIN, CAR], datetime(2026, 10, 12, 9, 15))
    assert entre["trains"] == [] and "Correspondance" in entre["message"]
    assert "terminé" in suivi.suivre([TRAIN, CAR], datetime(2026, 10, 12, 11, 0))["message"]
    assert suivi.suivre([MARCHE], HEURE)["trains"] == []                                                # à pied : pas de train


def test_profil_de_vitesse_accelere_croise_puis_freine():
    etat = suivi.profil(distance_m=20000, duree_s=600, acceleration=0.5)         # 20 km en 10 min : environ 120 km/h de croisière
    assert etat(0) == (0.0, 0.0)                                                   # à quai au départ
    assert etat(600)[0] == pytest.approx(20000) and etat(600)[1] == pytest.approx(0, abs=1e-6)       # à l'arrêt à l'arrivée, après tout le trajet
    assert etat(300)[0] == pytest.approx(10000)                                    # à mi-temps, à mi-chemin (profil symétrique)
    croisiere = etat(300)[1]
    assert croisiere == pytest.approx(38.2, abs=0.1) and croisiere > 20000 / 600                  # un peu au-dessus de la moyenne (33,3 m/s) : il faut rattraper l'accélération et le freinage
    vitesses = [etat(t)[1] for t in range(0, 601, 10)]
    assert max(vitesses) == pytest.approx(croisiere) and vitesses[1] < vitesses[3] < vitesses[10]   # elle monte au démarrage…
    assert vitesses[-2] < vitesses[-4] < vitesses[-11]                                              # … et redescend avant l'arrivée
    parcouru = [etat(t)[0] for t in range(0, 601, 10)]
    assert all(a <= b for a, b in zip(parcouru, parcouru[1:]))                                      # le train ne recule jamais


def test_profil_trop_serre_devient_triangulaire():
    etat = suivi.profil(distance_m=20000, duree_s=250, acceleration=0.1)           # horaire impossible avec 0,1 m/s² : on accélère plus fort
    assert etat(250)[0] == pytest.approx(20000)
    assert etat(125)[1] == pytest.approx(2 * 20000 / 250, rel=1e-6)               # pic au milieu : le double de la vitesse moyenne


def test_suivre_donne_la_vitesse_et_la_distance_restante():
    etat = suivi.suivre([TRAIN], HEURE + timedelta(minutes=30))
    train = etat["trains"][0]
    assert train["vitesse_kmh"] > 0 and 10 < train["reste_km"] < 12 and "km/h" in etat["message"] and "il reste" in etat["message"]
    debut = suivi.suivre([TRAIN], HEURE)["trains"][0]
    assert debut["vitesse_kmh"] == 0                                               # à quai à l'instant du départ


def test_horloge_simulee_accelere_le_temps():
    depart, t0 = datetime(2026, 10, 12, 8, 0), datetime(2026, 1, 1, 12, 0, 0)
    assert suivi.horloge_simulee(depart, t0, t0 + timedelta(seconds=30), vitesse=120) == datetime(2026, 10, 12, 9, 0)


def test_images_des_services():
    assert sprites.cle_sprite("inoui") == "inoui" and sprites.cle_sprite("ouigo") == "ouigo"
    assert sprites.cle_sprite("rer", "RER ZECO") == "rer" and sprites.cle_sprite("rer", "Transilien L") == "transilien"
    assert sprites.cle_sprite("intercites") == "ter" and sprites.cle_sprite("eurostar") == "inoui"      # pas d'image : la plus proche
    assert sprites.cle_sprite("bus") is None and sprites.cle_sprite("pied") is None


def test_chaque_image_est_un_png_recadre_sur_le_train():
    for cle in sprites.IMAGES:
        png = sprites.sprite_png(cle)
        assert png is not None and png[:8] == b"\x89PNG\r\n\x1a\n"
        assert 10 < sprites.largeur_sur_hauteur(cle) < 30                  # une bande fine : le filigrane en coin n'élargit pas le recadrage


def test_recadrage_ignore_les_petits_elements_isoles():
    masque = np.zeros((100, 400), dtype=bool)
    masque[45:55, 20:380] = True                                           # le train
    masque[90:95, 380:395] = True                                          # filigrane dans un coin
    assert sprites._zone_du_train(masque) == (20, 45, 380, 55)
