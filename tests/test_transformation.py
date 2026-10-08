"""Vérifie que transformation.py lance les étapes dans l'ordre et s'arrête à la première qui échoue."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src" / "transformation"))

import transformation


class Etape:
    def __init__(self, journal, nom, erreur=False):
        self.journal, self.nom, self.erreur = journal, nom, erreur

    def transformer(self):
        self.journal.append(self.nom)
        if self.erreur:
            raise RuntimeError(self.nom)


def test_lance_les_etapes_dans_l_ordre(monkeypatch):
    journal = []
    monkeypatch.setattr(transformation, "ETAPES", [("a", Etape(journal, "a")), ("b", Etape(journal, "b"))])
    transformation.transformer()
    assert journal == ["a", "b"]


def test_s_arrete_a_la_premiere_erreur(monkeypatch):
    journal = []
    monkeypatch.setattr(transformation, "ETAPES", [("a", Etape(journal, "a", erreur=True)), ("b", Etape(journal, "b"))])
    with pytest.raises(RuntimeError):
        transformation.transformer()
    assert journal == ["a"]


def test_les_gares_sont_la_premiere_etape():
    assert transformation.ETAPES[0][0] == "gares"
