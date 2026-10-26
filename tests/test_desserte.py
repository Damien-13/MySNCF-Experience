"""Vérifie les gares joignables en train (lib/desserte.py) sur des suites d'arrêts synthétiques."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib import desserte

# Train 1 : A → B → C ; train 2 : C → D ; train 3 : E → A (ne repart pas de A) ; train 4 : D → F (deux correspondances depuis A).
SUITES = [(1, 2, 3), (3, 4), (5, 1), (4, 6), (1, 2, 3)]
A, B, C, D, E, F = 1, 2, 3, 4, 5, 6


def test_direct_dans_le_sens_du_train():
    direct = desserte.construire(SUITES)
    assert direct[A] == {B, C} and direct[B] == {C}
    assert A not in direct.get(C, set())                     # le train ne revient pas en arrière


def test_correspondances():
    direct = desserte.construire(SUITES)
    assert desserte.atteintes(direct, A, 0) == {A, B, C}
    assert desserte.atteintes(direct, A, 1) == {A, B, C, D}    # changement à C
    assert desserte.atteintes(direct, A, 2) == {A, B, C, D, F}
    assert desserte.atteintes(direct, F, 1) == {F}              # aucun train ne part de F : la gare de départ seule
