"""Images des trains vues du dessus (assets/train/), recadrées en mémoire pour le dashboard. Les fichiers d'origine ne sont jamais modifiés.

Chaque image est un grand PNG avec le train en bande fine au centre : on garde le PNG sans fond quand il existe (le .jpeg a un fond blanc),
on recadre sur le train et on réduit pour l'afficher sur la carte.

Usage :
    cle = cle_sprite("inoui", "TGV INOUI 6106")     # « inoui », None pour un car (pas d'image) ou la marche
    png = sprite_png(cle)                           # octets du PNG, servis par le dashboard
    largeur_sur_hauteur(cle)                        # proportions pour dimensionner le repère
"""
import io
import unicodedata
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

DOSSIER = Path(__file__).resolve().parents[1] / "assets" / "train"
LARGEUR_PX = 700

# Image à utiliser par service ; chemin relatif à assets/train (les accents des dossiers varient selon le système : voir _trouver).
IMAGES = {
    "inoui": "inouï/inouï.png",
    "ouigo": "ouigo/ouigo.png",
    "ter": "ter/ter.png",
    "rer": "RER/rer.png",
    "transilien": "Transilien/Transilien.png",
    "renfe": "Renfe AVE/Renfe AVE.png",
    "trenitalia": "Frecciarossa/Frecciarossa.png",
}
# Longueur réelle d'une rame en mètres : l'image du train est affichée à cette échelle sur la carte (elle grandit quand on zoome).
LONGUEURS_M = {"inoui": 200, "ouigo": 200, "renfe": 200, "trenitalia": 200, "ter": 100, "rer": 110, "transilien": 100}
LONGUEUR_PAR_DEFAUT_M = 100
# Accélération typique en m/s² : un TGV démarre doucement, un RER ou un Transilien beaucoup plus vite (elle règle le profil de vitesse entre deux gares).
ACCELERATIONS = {"inoui": 0.5, "ouigo": 0.5, "renfe": 0.5, "trenitalia": 0.5, "ter": 0.8, "rer": 1.0, "transilien": 1.0}
ACCELERATION_PAR_DEFAUT = 0.7
# Services sans image : on prend la plus proche (un Intercités ressemble à un TER, les autres trains à grande vitesse à un INOUI).
REPLI = {"intercites": "ter", "eurostar": "inoui", "international": "inoui", "inconnu": "inoui"}


def cle_sprite(cle_style, libelle=""):
    """Clé de l'image d'un service (style_ligne()["cle"]) : None pour un car ou la marche, qui n'ont pas d'image de train."""
    if cle_style in ("bus", "pied", "velo_bus", "voiture"):
        return None
    if cle_style == "rer":
        return "rer" if "RER" in libelle.upper() else "transilien"
    return cle_style if cle_style in IMAGES else REPLI.get(cle_style, "inoui")


def infos(cle_style, libelle=""):
    """Ce dont le navigateur a besoin pour afficher un train : {"sprite": clé de l'image ou None, "longueur_m", "rapport" (largeur / hauteur de l'image), "acc" (accélération en m/s²)}."""
    cle = cle_sprite(cle_style, libelle)
    return {"sprite": cle, "longueur_m": LONGUEURS_M.get(cle, LONGUEUR_PAR_DEFAUT_M) if cle else 12, "rapport": largeur_sur_hauteur(cle) if cle else 1.0,
            "acc": ACCELERATIONS.get(cle, ACCELERATION_PAR_DEFAUT) if cle else 0.9}


def _normal(nom):
    return unicodedata.normalize("NFC", nom).casefold()


def _trouver(relatif):
    """Fichier de assets/train correspondant à un chemin relatif, sans tenir compte de la forme des accents (macOS les décompose), ou None."""
    chemin = DOSSIER
    for morceau in Path(relatif).parts:
        if not chemin.is_dir():
            return None
        suite = next((f for f in chemin.iterdir() if _normal(f.name) == _normal(morceau)), None)
        if suite is None:
            return None
        chemin = suite
    return chemin


def _zone_du_train(opaque):
    """(gauche, haut, droite, bas) de la bande du train dans un masque des pixels opaques : seules les lignes bien remplies comptent,
    ce qui écarte les petits éléments isolés (filigrane dans un coin)."""
    lignes = np.flatnonzero(opaque.sum(axis=1) > 0.2 * opaque.sum(axis=1).max())
    haut, bas = int(lignes[0]), int(lignes[-1]) + 1
    colonnes = np.flatnonzero(opaque[haut:bas].sum(axis=0) > 0)
    return int(colonnes[0]), haut, int(colonnes[-1]) + 1, bas


@lru_cache(maxsize=None)
def _image(cle):
    """Image recadrée sur le train, ou None si le fichier est absent."""
    fichier = _trouver(IMAGES[cle]) if cle in IMAGES else None
    if fichier is None:
        return None
    image = Image.open(fichier).convert("RGBA")
    image = image.crop(_zone_du_train(np.array(image.getchannel("A")) > 16))
    return image.resize((LARGEUR_PX, max(1, round(image.height * LARGEUR_PX / image.width))), Image.LANCZOS)


@lru_cache(maxsize=None)
def sprite_png(cle):
    """Octets du PNG recadré d'un service (clé de IMAGES), ou None."""
    image = _image(cle)
    if image is None:
        return None
    sortie = io.BytesIO()
    image.save(sortie, "PNG", optimize=True)
    return sortie.getvalue()


def largeur_sur_hauteur(cle):
    """Proportions (largeur / hauteur) de l'image recadrée, 20 si elle est absente."""
    image = _image(cle)
    return image.width / image.height if image else 20.0
