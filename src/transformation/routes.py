"""Transformation du réseau routier : lit l'extrait OpenStreetMap de la France (data/osm_france/*.osm.pbf), puis remplit troncon_route.

Usage : python src/transformation/routes.py
Relançable sans risque : les routes sont remplacées en entier (tout passe ou rien).

Sert à tracer un car arrêt par arrêt sur les routes (lib/reseau_routier.py) quand sa ligne OpenStreetMap manque ou est incomplète (voir lib/trace_bus.py).
Le fichier est lu une seule fois : un index des positions de tous les nœuds est écrit sur le disque (une dizaine de Go le temps du calcul), puis supprimé.

Nettoyage :
- Seules les routes où un car passe sont gardées (CLASSES) : ni pistes, ni chemins, ni voies de service, ni rues résidentielles (trop nombreuses : le car les rejoint depuis la route la plus proche).
- Les routes interdites aux autocars (accès « no » ou « private », sauf si les bus sont admis) sont écartées.
- Sens unique : tag oneway, ronds-points, autoroutes (sauf voie à contresens réservée aux bus).
- Chaque route est coupée à chaque carrefour (nœud partagé avec une autre route gardée) : un tronçon va d'un carrefour au suivant.
- Les coordonnées sont arrondies à 5 décimales (environ 1 m).
"""
import json
import sys
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np
import osmium
import sqlalchemy as sa

from lib.db.connection import get_engine
from lib.db.models import TronconRoute
from lib.reseau_ferre import KM_PAR_DEGRE_LAT, KM_PAR_DEGRE_LON
from lib.reseau_routier import tuile

DOSSIER_OSM = ROOT / "data" / "osm_france"
CLASSES = ("motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link",
           "tertiary", "tertiary_link", "unclassified", "busway")
ECHELLE = 100_000        # coordonnées en entiers : 5 décimales
OUI = ("yes", "designated", "official")
CHUNK_SIZE = 5_000


def sens_unique(tags):
    """0 double sens, 1 sens unique dans le sens du tracé, -1 sens unique dans le sens inverse."""
    if tags.get("oneway:bus") == "no" or tags.get("oneway:psv") == "no":
        return 0
    valeur = tags.get("oneway")
    if valeur == "-1":
        return -1
    if valeur in ("yes", "true", "1") or tags.get("junction") in ("roundabout", "circular"):
        return 1
    if valeur is None and tags.get("highway") in ("motorway", "motorway_link"):
        return 1
    return 0


def autocar_admis(tags):
    """Faux si la route est interdite aux autocars (accès « no » ou « private », sauf bus admis)."""
    if tags.get("bus") in OUI or tags.get("psv") in OUI or tags.get("highway") == "busway":
        return True
    if tags.get("bus") == "no" or tags.get("psv") == "no":
        return False
    return not (tags.get("access") in ("no", "private") or tags.get("motor_vehicle") in ("no", "private") or tags.get("area") == "yes")


class _Routes(osmium.SimpleHandler):
    """Lecture : les routes gardées, avec leurs nœuds (identifiant et position) mis bout à bout dans des tableaux compacts."""

    def __init__(self):
        super().__init__()
        self.ids, self.lons, self.lats = array("q"), array("i"), array("i")
        self.debuts = array("q", [0])        # début de chaque route dans les tableaux ci-dessus (+ la fin)
        self.classes, self.sens = [], array("b")

    def way(self, w):
        classe = w.tags.get("highway")
        if classe not in CLASSES or not autocar_admis(w.tags):
            return
        try:
            noeuds = [(n.ref, round(n.lon * ECHELLE), round(n.lat * ECHELLE)) for n in w.nodes]
        except osmium.InvalidLocationError:      # route qui sort de l'extrait
            return
        if len(noeuds) < 2:
            return
        sens = sens_unique(w.tags)
        if sens == -1:
            noeuds.reverse()
        for ref, lon, lat in noeuds:
            self.ids.append(ref)
            self.lons.append(lon)
            self.lats.append(lat)
        self.debuts.append(len(self.ids))
        self.classes.append(classe)
        self.sens.append(abs(sens))


def decouper(ids, lons, lats, debuts, classes, sens):
    """Tronçons d'un carrefour au suivant : liste de {« classe », « sens », « tuile », « geometrie », « longueur_m »}.
    ids, lons, lats : tableaux des nœuds de toutes les routes bout à bout ; debuts : début de chaque route (+ la fin) ; lons et lats en entiers (ECHELLE)."""
    ids, lons, lats, debuts = (np.asarray(a) for a in (ids, lons, lats, debuts))
    n = len(ids)
    if n == 0:
        return []
    route = np.repeat(np.arange(len(debuts) - 1), np.diff(debuts))      # route de chaque nœud
    _, retour, comptes = np.unique(ids, return_inverse=True, return_counts=True)
    coupe = comptes[retour] > 1                                          # nœud partagé : carrefour
    coupe[debuts[:-1]] = True
    coupe[debuts[1:] - 1] = True
    positions = np.flatnonzero(coupe)
    meme_route = route[positions[:-1]] == route[positions[1:]]
    debuts_t, fins_t = positions[:-1][meme_route], positions[1:][meme_route]
    tronçons = []
    for a, b in zip(debuts_t.tolist(), fins_t.tolist()):
        x, y = lons[a:b + 1] / ECHELLE, lats[a:b + 1] / ECHELLE
        longueur = float(np.hypot(np.diff(x) * KM_PAR_DEGRE_LON * 1000, np.diff(y) * KM_PAR_DEGRE_LAT * 1000).sum())
        milieu = (a + b) // 2
        r = int(route[a])
        tronçons.append({"classe": classes[r], "sens": int(sens[r]), "tuile": tuile(lons[milieu] / ECHELLE, lats[milieu] / ECHELLE),
                         "geometrie": json.dumps(np.column_stack([x, y]).tolist(), separators=(",", ":")), "longueur_m": round(longueur, 1)})
    return tronçons


def lire(fichier, index):
    """Lit le fichier .osm.pbf avec un index des nœuds écrit dans `index` : tronçons prêts à insérer."""
    routes = _Routes()
    routes.apply_file(str(fichier), locations=True, idx=f"sparse_file_array,{index}")
    print(f"  {len(routes.classes)} routes gardées, {len(routes.ids)} nœuds")
    return decouper(routes.ids, routes.lons, routes.lats, routes.debuts, routes.classes, routes.sens)


def charger(troncons, engine=None):
    """Remplace en une transaction tout le réseau routier. Retourne le nombre de tronçons chargés."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(sa.delete(TronconRoute))
        for i in range(0, len(troncons), CHUNK_SIZE):
            conn.execute(sa.insert(TronconRoute), troncons[i:i + CHUNK_SIZE])
    return len(troncons)


def transformer():
    """Lit le fichier OpenStreetMap, découpe aux carrefours, charge. L'index des nœuds est supprimé à la fin."""
    fichiers = sorted(DOSSIER_OSM.glob("*.osm.pbf"))
    if not fichiers:
        sys.exit(f"Aucun fichier .osm.pbf dans {DOSSIER_OSM} (source osm_france : python src/initialize.py)")
    index = DOSSIER_OSM / "index_noeuds.tmp"
    try:
        troncons = lire(fichiers[-1], index)
    finally:
        index.unlink(missing_ok=True)
    nb = charger(troncons)
    print(f"Routes : {nb} tronçons chargés")
    return nb


if __name__ == "__main__":
    transformer()
