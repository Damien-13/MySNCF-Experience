"""Transformation du tracé des lignes de bus : lit l'extrait OpenStreetMap de la France (data/osm_france/*.osm.pbf), puis remplit ligne_bus.

Usage : python src/transformation/lignes_bus.py
Relançable sans risque : les lignes sont remplacées en entier (tout passe ou rien).

Une ligne = une relation OSM route=bus (cars interurbains et réseaux urbains). Le fichier est trop gros pour garder tous les nœuds en mémoire : trois lectures.
1. Les relations route=bus : étiquettes et tronçons (ways) qui les composent.
2. Ces tronçons : les nœuds qui les composent.
3. Ces nœuds : leurs coordonnées.

Nettoyage :
- Seuls les tronçons de route (rôle vide, « forward » ou « backward ») sont gardés : arrêts et quais (« stop », « platform ») sont écartés.
- Les tronçons bout à bout sont fusionnés en polylignes, puis simplifiés (TOLERANCE_DEG, environ 5 m) et arrondis à 5 décimales (environ 1 m).
- Une ligne sans tracé, ou de moins de LONGUEUR_MIN_KM, est écartée.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import osmium
import sqlalchemy as sa
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge

from lib.db.connection import get_engine
from lib.db.models import LigneBus
from lib.reseau_ferre import DECIMALES, longueur_km

DOSSIER_OSM = ROOT / "data" / "osm_france"
ROLES_ROUTE = {"", "forward", "backward"}
TOLERANCE_DEG = 0.00005
LONGUEUR_MIN_KM = 0.3
CHUNK_SIZE = 2_000


class _Relations(osmium.SimpleHandler):
    """Lecture 1 : les relations route=bus et leurs tronçons."""

    def __init__(self):
        super().__init__()
        self.lignes = {}      # id de la relation -> {"tags": {...}, "troncons": [id de way, …]}

    def relation(self, r):
        if r.tags.get("route") != "bus":
            return
        troncons = [m.ref for m in r.members if m.type == "w" and m.role in ROLES_ROUTE]
        if troncons:
            tags = {k: r.tags.get(k) for k in ("ref", "name", "network", "operator", "from", "to")}
            self.lignes[r.id] = {"tags": tags, "troncons": troncons}


class _Troncons(osmium.SimpleHandler):
    """Lecture 2 : les nœuds des tronçons demandés."""

    def __init__(self, voulus):
        super().__init__()
        self.voulus = voulus
        self.noeuds = {}      # id du way -> [id de nœud, …]

    def way(self, w):
        if w.id in self.voulus:
            self.noeuds[w.id] = [n.ref for n in w.nodes]


class _Noeuds(osmium.SimpleHandler):
    """Lecture 3 : les coordonnées des nœuds demandés."""

    def __init__(self, voulus):
        super().__init__()
        self.voulus = voulus
        self.coord = {}       # id du nœud -> (lon, lat)

    def node(self, n):
        if n.id in self.voulus:
            self.coord[n.id] = (n.location.lon, n.location.lat)


def lire(fichier):
    """Lit le fichier .osm.pbf : une liste de {« id », « tags », « troncons »: [[(lon, lat), …], …]}, un tronçon par way de la relation."""
    relations = _Relations()
    relations.apply_file(str(fichier))
    print(f"  1/3 {len(relations.lignes)} relations route=bus")
    voulus = {w for l in relations.lignes.values() for w in l["troncons"]}
    troncons = _Troncons(voulus)
    troncons.apply_file(str(fichier))
    print(f"  2/3 {len(troncons.noeuds)} tronçons sur {len(voulus)} demandés")
    noeuds = {n for ids in troncons.noeuds.values() for n in ids}
    coordonnees = _Noeuds(noeuds)
    coordonnees.apply_file(str(fichier))
    print(f"  3/3 {len(coordonnees.coord)} nœuds sur {len(noeuds)} demandés")
    lignes = []
    for id_, l in relations.lignes.items():
        parties = []
        for w in l["troncons"]:
            points = [coordonnees.coord[n] for n in troncons.noeuds.get(w, []) if n in coordonnees.coord]
            if len(points) >= 2:
                parties.append(points)
        lignes.append({"id": id_, "tags": l["tags"], "troncons": parties})
    return lignes


def _polylignes(troncons):
    """Tronçons fusionnés bout à bout, simplifiés et arrondis : liste de polylignes [[lon, lat], …] (vide s'il n'y a rien d'exploitable)."""
    fusion = linemerge(MultiLineString([LineString(t) for t in troncons]))
    morceaux = list(fusion.geoms) if fusion.geom_type == "MultiLineString" else [fusion]
    sorties = []
    for morceau in morceaux:
        arrondis = [[round(lon, DECIMALES), round(lat, DECIMALES)] for lon, lat in morceau.simplify(TOLERANCE_DEG).coords]
        if len(arrondis) >= 2 and arrondis[0] != arrondis[-1]:
            sorties.append(arrondis)
    return sorties


def nettoyer(lignes):
    """Une ligne par relation avec tracé, prête à insérer dans ligne_bus."""
    out = []
    for l in lignes:
        if not l["troncons"]:
            continue
        polylignes = _polylignes(l["troncons"])
        km = sum(longueur_km(p) for p in polylignes)
        if not polylignes or km < LONGUEUR_MIN_KM:
            continue
        lons = [p[0] for poly in polylignes for p in poly]
        lats = [p[1] for poly in polylignes for p in poly]
        t = l["tags"]
        out.append({"id": l["id"], "ref": t["ref"], "nom": t["name"], "reseau": t["network"], "exploitant": t["operator"],
                    "de": t["from"], "vers": t["to"], "geometrie": json.dumps(polylignes, separators=(",", ":")),
                    "longueur_km": round(km, 3), "lat_min": min(lats), "lat_max": max(lats), "lon_min": min(lons), "lon_max": max(lons)})
    return out


def charger(lignes, engine=None):
    """Remplace en une transaction toutes les lignes de bus. Retourne le nombre de lignes chargées."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(sa.delete(LigneBus))
        for i in range(0, len(lignes), CHUNK_SIZE):
            conn.execute(sa.insert(LigneBus), lignes[i:i + CHUNK_SIZE])
    return len(lignes)


def transformer():
    """Lit le fichier OpenStreetMap, nettoie, charge, et affiche ce qui a été écarté."""
    fichiers = sorted(DOSSIER_OSM.glob("*.osm.pbf"))
    if not fichiers:
        sys.exit(f"Aucun fichier .osm.pbf dans {DOSSIER_OSM} (source osm_france : python src/initialize.py)")
    brut = lire(fichiers[-1])
    lignes = nettoyer(brut)
    nb = charger(lignes)
    print(f"Lignes de bus : {nb} chargées ({len(brut)} relations lues, {len(brut) - nb} sans tracé ou de moins de {LONGUEUR_MIN_KM} km)")
    return nb


if __name__ == "__main__":
    transformer()
