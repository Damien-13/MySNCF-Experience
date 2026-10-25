"""Choix des gares et acheminement jusqu'à une gare relais, d'après les horaires de la base (sans dépendance à Dash).

- Ville de destination : on vise la gare de la ville où arrivent des trains directs depuis le départ (ou depuis sa gare relais),
  sinon la plus desservie. Les gares n'ont pas de commune en base : ce sont celles à moins de RAYON_VILLE_KM du centre de la ville.
- Gare relais : quand la gare de départ n'a pas de train direct vers la zone d'arrivée mais qu'une gare proche en a (Aix-en-Provence → Aix TGV),
  on propose aussi d'y aller en car (lignes de bus de la base, arrêts à moins de RAYON_ARRET_KM des deux gares), sinon en voiture,
  puis de prendre le train à la gare relais. Le trajet en train est demandé à l'API SNCF par lib/itineraire.py.

Les sections produites ont le même format que celles de lib/navitia.py (type, mode, de, vers, depart, arrivee, duree_s, ligne, numero…).

Usage :
    from lib.acheminement import gare_de_ville, gare_relais, acheminer, assembler
    gare_de_ville(engine, 48.857, 2.35, [id_gare_depart])          # id de la gare d'arrivée à viser dans la ville
    relais = gare_relais(engine, id_gare_depart, id_gare_arrivee)    # dict de la gare relais, ou None
    sections = acheminer(engine, gare_depart, relais, apres=datetime(2026, 10, 27, 13, 0))
"""
import math
from datetime import datetime, timedelta

import pandas as pd
import sqlalchemy as sa

KM_PAR_DEGRE_LAT = 110.57
RAYON_VILLE_KM = 8               # gares d'une ville : autour de son centre (Paris intra-muros tient dans ce rayon)
RAYON_RELAIS_KM = 25             # gare relais : une gare TGV en périphérie (Aix TGV est à 14 km de la gare d'Aix)
RAYON_ZONE_ARRIVEE_KM = 15       # le relais doit avoir un train direct vers une gare de cette zone autour de l'arrivée
RAYON_ARRET_KM = 0.5             # arrêt de car utilisable pour une gare
VITESSE_MARCHE_M_MIN = 80
VITESSE_VOITURE_KM_H = 50
DETOUR_ROUTE = 1.3               # la route est plus longue que la ligne droite
MARGE_CORRESPONDANCE = timedelta(minutes=10)
MIN_TRAINS_RELAIS = 3            # un relais doit avoir au moins ce nombre de trains directs vers la zone d'arrivée
CO2_G_PAR_KM = {"bus": 113, "car": 218}     # par voyageur, ordre de grandeur de la Base Empreinte de l'ADEME (bus thermique, voiture seule)


def _km(lat1, lon1, lat2, lon2):
    return math.hypot((lat2 - lat1) * KM_PAR_DEGRE_LAT, (lon2 - lon1) * 111.32 * math.cos(math.radians(lat1)))


def _boite(lat, lon, rayon_km):
    dlat, dlon = rayon_km / KM_PAR_DEGRE_LAT, rayon_km / (111.32 * math.cos(math.radians(lat)))
    return {"lat1": lat - dlat, "lat2": lat + dlat, "lon1": lon - dlon, "lon2": lon + dlon}


def gares_proches(engine, lat, lon, rayon_km):
    """Gares connues de l'API (code UIC) à moins de `rayon_km` : DataFrame id, nom, lat, lon, code_uic, km, la plus proche d'abord."""
    df = pd.read_sql(sa.text("SELECT lieu.id, lieu.nom, lieu.lat, lieu.lon, gare.code_uic FROM lieu JOIN gare ON gare.lieu_id = lieu.id "
                             "WHERE gare.code_uic IS NOT NULL AND lieu.lat BETWEEN :lat1 AND :lat2 AND lieu.lon BETWEEN :lon1 AND :lon2"),
                     engine, params=_boite(lat, lon, rayon_km))
    df["km"] = [_km(lat, lon, a, b) for a, b in zip(df["lat"], df["lon"])]
    return df[df["km"] <= rayon_km].sort_values("km").reset_index(drop=True)


def trains_directs(engine, departs, arrivees):
    """Nombre de circulations qui passent par une gare de `departs` puis par une gare de `arrivees` : DataFrame depart, arrivee, n (le plus desservi d'abord)."""
    departs, arrivees = [int(i) for i in departs], [int(i) for i in arrivees]
    if not departs or not arrivees:
        return pd.DataFrame(columns=["depart", "arrivee", "n"])
    requete = sa.text(
        "SELECT a1.lieu_id AS depart, a2.lieu_id AS arrivee, COUNT(DISTINCT p1.circulation_id) AS n "
        "FROM arret a1 JOIN passage p1 ON p1.arret_id = a1.id "
        "JOIN passage p2 ON p2.circulation_id = p1.circulation_id AND p2.ordre > p1.ordre JOIN arret a2 ON a2.id = p2.arret_id "
        "WHERE a1.lieu_id IN :departs AND a2.lieu_id IN :arrivees AND a1.lieu_id != a2.lieu_id GROUP BY 1, 2 ORDER BY n DESC"
    ).bindparams(sa.bindparam("departs", expanding=True), sa.bindparam("arrivees", expanding=True))
    return pd.read_sql(requete, engine, params={"departs": departs, "arrivees": arrivees})


def _desserte(engine, gares):
    """Nombre de circulations par gare : {id: n}."""
    gares = [int(i) for i in gares]
    if not gares:
        return {}
    df = pd.read_sql(sa.text("SELECT a.lieu_id AS id, COUNT(DISTINCT p.circulation_id) AS n FROM arret a JOIN passage p ON p.arret_id = a.id "
                             "WHERE a.lieu_id IN :gares GROUP BY 1").bindparams(sa.bindparam("gares", expanding=True)), engine, params={"gares": gares})
    return dict(zip(df["id"].astype(int), df["n"].astype(int)))


def gare_de_ville(engine, lat, lon, departs):
    """Gare à viser pour une ville (centre lat, lon) depuis les gares `departs` : celle qui reçoit le plus de trains directs,
    sinon la plus desservie de la ville, sinon la plus proche. None s'il n'y a aucune gare autour."""
    gares = gares_proches(engine, lat, lon, RAYON_VILLE_KM)
    if gares.empty:
        return None
    directs = trains_directs(engine, departs, gares["id"])
    if not directs.empty:
        return int(directs.groupby("arrivee")["n"].sum().idxmax())
    desserte = _desserte(engine, gares["id"])
    return int(max(gares["id"], key=lambda i: desserte.get(int(i), 0))) if desserte else int(gares.iloc[0]["id"])


def gare_relais(engine, depart, arrivee):
    """Gare la plus proche du départ (dict lieu : id, nom, lat, lon, code_uic) d'où partent des trains directs vers la zone d'arrivée,
    quand la gare de départ n'en a pas (Aix-en-Provence → Aix TGV plutôt que Marseille). `depart`, `arrivee` : dicts lieu des gares. None si le relais n'apporte rien."""
    zone = gares_proches(engine, arrivee["lat"], arrivee["lon"], RAYON_ZONE_ARRIVEE_KM)["id"]
    if not trains_directs(engine, [depart["id"]], zone).empty:
        return None
    voisines = gares_proches(engine, depart["lat"], depart["lon"], RAYON_RELAIS_KM)
    voisines = voisines[voisines["id"] != depart["id"]]
    directs = trains_directs(engine, voisines["id"], zone)
    if directs.empty:
        return None
    servies = directs.groupby("depart")["n"].sum()
    servies = set(servies[servies >= MIN_TRAINS_RELAIS].index)
    if not servies:
        return None
    relais = voisines[voisines["id"].isin(servies)].iloc[0]          # voisines est triée de la plus proche à la plus loin
    return {"id": int(relais["id"]), "nom": relais["nom"], "lat": float(relais["lat"]), "lon": float(relais["lon"]), "code_uic": relais["code_uic"]}


def _arrets(engine, gare):
    """Arrêts de bus ou de car à moins de RAYON_ARRET_KM d'une gare : {id d'arrêt: (lon, lat, distance en km)}."""
    df = pd.read_sql(sa.text("SELECT a.id, l.lat, l.lon FROM arret a JOIN lieu l ON l.id = a.lieu_id WHERE l.type = 'arret_bus' "
                             "AND l.lat BETWEEN :lat1 AND :lat2 AND l.lon BETWEEN :lon1 AND :lon2"),
                     engine, params=_boite(gare["lat"], gare["lon"], RAYON_ARRET_KM))
    proches = {}
    for i, a, b in zip(df["id"], df["lat"], df["lon"]):
        km = _km(gare["lat"], gare["lon"], a, b)
        if km <= RAYON_ARRET_KM:
            proches[i] = (float(b), float(a), km)
    return proches


def _marche(de_nom, de_lonlat, vers_nom, vers_lonlat, km, depart):
    duree = timedelta(minutes=max(1, round(km * 1000 / VITESSE_MARCHE_M_MIN)))
    return {"type": "street_network", "mode": "walking", "duree_s": int(duree.total_seconds()), "de": de_nom, "vers": vers_nom,
            "de_lonlat": de_lonlat, "vers_lonlat": vers_lonlat, "arrets_lonlat": [], "depart": depart, "arrivee": depart + duree,
            "ligne": None, "numero": None, "direction": None, "reseau": None, "mode_physique": None, "temps_reel": False, "retard_min": 0}


def _prochain_car(engine, arrets_de, arrets_vers, apres, au_plus_tard=None):
    """Circulation de car ou de bus qui part d'un arrêt de `arrets_de` à partir de `apres` (datetime) et passe ensuite par un arrêt de `arrets_vers`
    le même jour : la première, ou avec `au_plus_tard` la dernière qui arrive avant cette heure (pour attendre le moins possible le train). dict ou None.
    Les heures de passage sont en secondes depuis minuit."""
    requete = sa.text(
        "SELECT c.id, c.numero, c.destination, li.nom AS ligne, li.type_transport, r.nom AS reseau, p1.arret_id AS de_id, p1.heure_depart, p1.ordre AS o1, "
        "p2.arret_id AS vers_id, p2.heure_arrivee, p2.ordre AS o2, a1.nom AS de_nom, a2.nom AS vers_nom "
        "FROM passage p1 JOIN passage p2 ON p2.circulation_id = p1.circulation_id AND p2.ordre > p1.ordre "
        "JOIN circulation c ON c.id = p1.circulation_id JOIN calendrier k ON k.service_id = c.service_id AND k.date = :jour "
        "JOIN ligne li ON li.id = c.ligne_id JOIN reseau r ON r.id = li.reseau_id JOIN arret a1 ON a1.id = p1.arret_id JOIN arret a2 ON a2.id = p2.arret_id "
        "WHERE p1.arret_id IN :de AND p2.arret_id IN :vers AND p1.heure_depart >= :seconde AND p2.heure_arrivee <= :limite "
        f"ORDER BY {'p2.heure_arrivee DESC' if au_plus_tard else 'p2.heure_arrivee'} LIMIT 1"
    ).bindparams(sa.bindparam("de", expanding=True), sa.bindparam("vers", expanding=True))
    minuit = datetime.combine(apres.date(), datetime.min.time())
    df = pd.read_sql(requete, engine, params={"de": list(arrets_de), "vers": list(arrets_vers), "jour": apres.date().isoformat(),
                                              "seconde": int((apres - minuit).total_seconds()),
                                              "limite": int((au_plus_tard - minuit).total_seconds()) if au_plus_tard else 10 ** 6})
    if df.empty:
        return None
    car = df.iloc[0].to_dict()
    points = pd.read_sql(sa.text("SELECT l.lon, l.lat FROM passage p JOIN arret a ON a.id = p.arret_id JOIN lieu l ON l.id = a.lieu_id "
                                 "WHERE p.circulation_id = :c AND p.ordre BETWEEN :o1 AND :o2 ORDER BY p.ordre"),
                         engine, params={"c": car["id"], "o1": int(car["o1"]), "o2": int(car["o2"])})
    car["arrets_lonlat"] = [(float(a), float(b)) for a, b in zip(points["lon"], points["lat"])]
    car["depart"] = minuit + timedelta(seconds=int(car["heure_depart"]))
    car["arrivee"] = minuit + timedelta(seconds=int(car["heure_arrivee"]))
    return car


def acheminer(engine, de, vers, apres, au_plus_tard=None):
    """Sections pour aller de la gare `de` à la gare `vers` (dicts lieu) en partant à partir de `apres` : à pied jusqu'à l'arrêt, car ou bus, à pied jusqu'à la gare.
    `au_plus_tard` : arriver avant cette heure en partant le plus tard possible (le train à prendre au relais). Sans car, une section en voiture
    (durée estimée, calée sur `au_plus_tard` s'il est donné). Liste de sections au format de lib/navitia.py."""
    arrets_de, arrets_vers = _arrets(engine, de), _arrets(engine, vers)
    car = _prochain_car(engine, arrets_de, arrets_vers, apres, au_plus_tard) if arrets_de and arrets_vers else None
    if car is None:
        km = _km(de["lat"], de["lon"], vers["lat"], vers["lon"]) * DETOUR_ROUTE
        duree = timedelta(minutes=round(km / VITESSE_VOITURE_KM_H * 60))
        apres = max(apres, au_plus_tard - duree) if au_plus_tard else apres
        return [{"type": "street_network", "mode": "car", "duree_s": int(duree.total_seconds()), "de": de["nom"], "vers": vers["nom"],
                 "de_lonlat": (de["lon"], de["lat"]), "vers_lonlat": (vers["lon"], vers["lat"]), "arrets_lonlat": [], "depart": apres, "arrivee": apres + duree,
                 "ligne": None, "numero": None, "direction": None, "reseau": None, "mode_physique": "Voiture", "temps_reel": False, "retard_min": 0,
                 "co2_g": round(km * CO2_G_PAR_KM["car"])}]
    lon1, lat1, km1 = arrets_de[car["de_id"]]
    lon2, lat2, km2 = arrets_vers[car["vers_id"]]
    aller = _marche(de["nom"], (de["lon"], de["lat"]), car["de_nom"], (lon1, lat1), km1, car["depart"] - timedelta(minutes=max(1, round(km1 * 1000 / VITESSE_MARCHE_M_MIN))))
    km_car = sum(_km(a[1], a[0], b[1], b[0]) for a, b in zip(car["arrets_lonlat"], car["arrets_lonlat"][1:]))
    trajet_car = {"type": "public_transport", "mode": "bus", "duree_s": int((car["arrivee"] - car["depart"]).total_seconds()), "de": car["de_nom"], "vers": car["vers_nom"],
                  "de_lonlat": (lon1, lat1), "vers_lonlat": (lon2, lat2), "arrets_lonlat": car["arrets_lonlat"], "depart": car["depart"], "arrivee": car["arrivee"],
                  "ligne": car["ligne"], "numero": car["numero"], "direction": car["destination"], "reseau": car["reseau"],
                  "mode_physique": "Car" if "car" in str(car["type_transport"]).lower() else "Bus", "temps_reel": False, "retard_min": 0,
                  "co2_g": round(km_car * CO2_G_PAR_KM["bus"])}
    fin = _marche(car["vers_nom"], (lon2, lat2), vers["nom"], (vers["lon"], vers["lat"]), km2, car["arrivee"])
    return [aller, trajet_car, fin]


def assembler(avant, trajet, apres=()):
    """Un trajet de l'API SNCF précédé (`avant`) ou suivi (`apres`) de sections d'acheminement : départ, arrivée, durée, correspondances et CO2 recalculés."""
    sections = [*avant, *trajet["sections"], *apres]
    depart = avant[0]["depart"] if avant else trajet["depart"]
    arrivee = apres[-1]["arrivee"] if apres else trajet["arrivee"]
    vehicules = [s for s in [*avant, *apres] if s["type"] == "public_transport" or s.get("mode") == "car"]
    co2 = (trajet.get("co2_g") or 0) + sum(s.get("co2_g") or 0 for s in vehicules)
    return {**trajet, "sections": sections, "depart": depart, "arrivee": arrivee, "duree_s": int((arrivee - depart).total_seconds()),
            "correspondances": trajet["correspondances"] + len(vehicules), "co2_g": co2 or None, "via": True}
