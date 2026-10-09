"""Transformation du tracé ferroviaire : nettoie les shapefiles de SNCF Réseau, puis remplit troncon_voie.

Usage : python src/transformation/voies.py
Relançable sans risque : le tracé est remplacé en entier (tout passe ou rien).

Deux sources, toutes deux en WGS84 (pas de reprojection) :
- formes_voies_rfn : une polyligne par voie (précision métrique). Source principale (source « voies »).
- formes_lignes_rfn : une polyligne par ligne (précision ~10 m). Elle complète les voies là où une ligne exploitée n'en a aucune (source « lignes »).

Nettoyage :
- Voies : les voies de service (VS : garages, faisceaux) sont écartées, on garde les voies principales (VPL, VPA).
- Lignes : seules les lignes exploitées (mnemo EXPLOITE) sont gardées ; fermées, neutralisées, déclassées ou retranchées ne sont plus utilisables.
  Une ligne n'est ajoutée que si son code_ligne n'a aucune voie gardée.
- Une entité à plusieurs parties donne un tronçon par partie. Une partie de moins de deux points est écartée.
- Les points sont simplifiés (TOLERANCE_DEG, environ 5 m) puis arrondis à 5 décimales (environ 1 m) pour alléger la base.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import shapefile
import sqlalchemy as sa
from shapely.geometry import LineString

from lib.db.connection import get_engine
from lib.db.models import TronconVoie
from lib.reseau_ferre import DECIMALES, longueur_km

DOSSIER_VOIES = ROOT / "data" / "formes_voies_rfn"
DOSSIER_LIGNES = ROOT / "data" / "formes_lignes_rfn"
TYPES_VOIE_GARDES = {"VPL", "VPA"}
MNEMO_LIGNE_EXPLOITEE = "EXPLOITE"
TOLERANCE_DEG = 0.00005
CHUNK_SIZE = 5_000


def lire(dossier):
    """Lit le shapefile du dossier : une liste d'entités {« attributs »: dict, « parties »: [[(lon, lat), …], …]}."""
    fichier = next(Path(dossier).glob("*.shp"))
    with shapefile.Reader(str(fichier), encoding="utf-8") as lecteur:
        entites = []
        for forme, enregistrement in zip(lecteur.shapes(), lecteur.records()):
            debuts = list(forme.parts) + [len(forme.points)]
            parties = [forme.points[debuts[i]:debuts[i + 1]] for i in range(len(forme.parts))]
            entites.append({"attributs": enregistrement.as_dict(), "parties": parties})
    return entites


def _simplifier(points):
    """Points simplifiés et arrondis, ou None si la partie a moins de deux points distincts."""
    if len(points) < 2:
        return None
    simple = list(LineString(points).simplify(TOLERANCE_DEG).coords)
    arrondis = [[round(lon, DECIMALES), round(lat, DECIMALES)] for lon, lat in simple]
    return arrondis if len(arrondis) >= 2 and arrondis[0] != arrondis[-1] else None


def _troncons(entites, source, type_voie=lambda a: None, nom_voie=lambda a: None):
    """Un dict par partie valide, prêt à insérer dans troncon_voie."""
    out = []
    for e in entites:
        a = e["attributs"]
        for partie in e["parties"]:
            points = _simplifier(partie)
            if points:
                out.append({"source": source, "code_ligne": str(a["code_ligne"]).strip(), "type_voie": type_voie(a),
                            "nom_voie": nom_voie(a), "geometrie": json.dumps(points, separators=(",", ":")),
                            "longueur_km": round(longueur_km(points), 3)})
    return out


def nettoyer_voies(entites):
    """Tronçons des voies principales (voies de service écartées)."""
    gardees = [e for e in entites if str(e["attributs"].get("type_voie", "")).strip() in TYPES_VOIE_GARDES]
    return _troncons(gardees, "voies", type_voie=lambda a: str(a["type_voie"]).strip(), nom_voie=lambda a: str(a.get("nom_voie") or "").strip() or None)


def completer_avec_lignes(entites, voies):
    """Tronçons des lignes exploitées dont le code_ligne n'a aucune voie dans `voies` (liste de tronçons déjà nettoyés)."""
    couvertes = {t["code_ligne"] for t in voies}
    exploitees = [e for e in entites if str(e["attributs"].get("mnemo", "")).strip() == MNEMO_LIGNE_EXPLOITEE
                  and str(e["attributs"]["code_ligne"]).strip() not in couvertes]
    return _troncons(exploitees, "lignes")


def charger(troncons, engine=None):
    """Remplace en une transaction tout le tracé. Retourne le nombre de tronçons chargés."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(sa.delete(TronconVoie))
        for i in range(0, len(troncons), CHUNK_SIZE):
            conn.execute(sa.insert(TronconVoie), troncons[i:i + CHUNK_SIZE])
    return len(troncons)


def transformer():
    """Lit les deux shapefiles, nettoie, complète, charge, et affiche ce qui a été écarté."""
    brut_voies, brut_lignes = lire(DOSSIER_VOIES), lire(DOSSIER_LIGNES)
    voies = nettoyer_voies(brut_voies)
    lignes = completer_avec_lignes(brut_lignes, voies)
    nb = charger(voies + lignes)
    print(f"Voies : {len(voies)} tronçons chargés ({len(brut_voies)} voies lues, voies de service écartées)")
    print(f"Lignes : {len(lignes)} tronçons ajoutés pour les lignes exploitées sans voie "
          f"({len({t['code_ligne'] for t in lignes})} lignes, sur {len(brut_lignes)} lues)")
    return nb


if __name__ == "__main__":
    transformer()
