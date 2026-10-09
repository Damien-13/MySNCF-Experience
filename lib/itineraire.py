"""Logique de l'onglet « Itinéraire voyageur » du dashboard : du lieu de départ (une gare) à la destination (un lieu de culture, de tourisme
ou un événement), sans dépendance à Dash.

Usage :
    from lib.itineraire import options_gares, chercher_destinations, rechercher
    options_gares()                                          # [{"label": nom, "value": id du lieu}, …]
    chercher_destinations("chambord", "culture")             # même format, 50 résultats au plus
    r = rechercher(depart_id, destination_id, quand="2026-10-12 08:00", retour="2026-10-14 18:00")

rechercher() retourne un dict (None si un lieu est inconnu) : depart, destination, gare_arrivee, distance_km (destination → gare la plus proche),
alentours (stations vélo et arrêts de bus près de la gare d'arrivée), dernier_km (mode, détail), faisable, trajets (aller, Navitia, jusqu'à 3),
trajets_retour (idem pour le retour, vide sans date de retour), meme_gare (la gare d'arrivée est celle du départ : pas de train), erreur_api (texte, sinon None), pois (lieux de toutes les catégories autour de la destination : le dashboard filtre à l'affichage).
tracer_trajet() dessine un trajet : un tracé collé aux voies par train, avec la couleur et les tirets du service (style_ligne).
Rien n'est stocké : l'API Navitia est appelée à chaque recherche (voir lib/navitia.py).
"""
import math
import re
from datetime import datetime, time

import pandas as pd
import sqlalchemy as sa

from lib import navitia
from lib.db.connection import get_engine
from lib.reseau_ferre import chemin

SEUIL_PIED_KM = 1.5
SEUIL_VELO_BUS_KM = 5.0
VITESSE_MARCHE_M_MIN = 80
RAYON_ALENTOURS_KM = 0.5
RAYON_POI_KM = 5.0
MAX_POI = 60            # par catégorie : le dashboard filtre ensuite sans nouvelle recherche
MAX_TRAJETS = 3
KM_PAR_DEGRE_LAT = 110.57
HEURE_DEFAUT = time(8, 0)
TYPES_POI = {"tous": ("tourisme", "culture", "evenement"), "culture": ("culture",), "tourisme": ("tourisme",), "evenement": ("evenement",)}


def _types(categorie):
    return TYPES_POI.get(categorie, TYPES_POI["tous"])


def options_gares(engine=None):
    """Gares pour le menu de départ : label = nom, value = id du lieu."""
    df = pd.read_sql(sa.text("SELECT id, nom FROM lieu WHERE type = 'gare' AND nom IS NOT NULL ORDER BY nom"), engine or get_engine())
    return [{"label": nom, "value": int(i)} for i, nom in zip(df["id"], df["nom"])]


def chercher_destinations(texte, categorie="tous", engine=None, inclure=None, limite=50):
    """Lieux de la catégorie dont le nom contient `texte` (au plus `limite`, commune en plus pour distinguer les homonymes).
    `inclure` : id d'un lieu à garder dans la liste (celui déjà choisi), sinon le menu le perd."""
    types = _types(categorie)
    where, ordre, params = "type IN :types AND nom IS NOT NULL", "nom", {"types": list(types), "limite": limite}
    if texte and texte.strip():
        where += " AND nom LIKE :texte"
        ordre = "nom NOT LIKE :debut, nom"                       # les noms qui commencent par la saisie d'abord
        params.update(texte=f"%{texte.strip()}%", debut=f"{texte.strip()}%")
    requete = sa.text(f"SELECT id, nom, commune FROM lieu WHERE {where} ORDER BY {ordre} LIMIT :limite").bindparams(sa.bindparam("types", expanding=True))
    df = pd.read_sql(requete, engine or get_engine(), params=params)
    if inclure is not None and int(inclure) not in set(df["id"]):
        df = pd.concat([pd.read_sql(sa.text("SELECT id, nom, commune FROM lieu WHERE id = :id"), engine or get_engine(), params={"id": int(inclure)}), df])
    return [{"label": f"{nom} ({commune})" if commune else nom, "value": int(i)} for i, nom, commune in zip(df["id"], df["nom"], df["commune"])]


def _lieu(engine, lieu_id):
    df = pd.read_sql(sa.text(
        "SELECT lieu.id, lieu.type, lieu.nom, lieu.commune, lieu.lat, lieu.lon, lieu.gare_proche_id, lieu.distance_gare_km, gare.code_uic "
        "FROM lieu LEFT JOIN gare ON gare.lieu_id = lieu.id WHERE lieu.id = :id"), engine, params={"id": int(lieu_id)})
    if df.empty:
        return None
    ligne = df.iloc[0].astype(object).where(df.iloc[0].notna(), None).to_dict()
    ligne["id"] = int(ligne["id"])
    return ligne


def alentours(engine, lat, lon, rayon_km=RAYON_ALENTOURS_KM):
    """Nombre de stations vélo et d'arrêts de bus à moins de `rayon_km` d'une position : {"velo": n, "bus": n}."""
    dlat, dlon = rayon_km / KM_PAR_DEGRE_LAT, rayon_km / (111.32 * math.cos(math.radians(lat)))
    df = pd.read_sql(sa.text(
        "SELECT type, COUNT(*) AS n FROM lieu WHERE type IN ('station_velo', 'arret_bus') AND lat BETWEEN :lat1 AND :lat2 "
        "AND lon BETWEEN :lon1 AND :lon2 GROUP BY type"),
        engine, params={"lat1": lat - dlat, "lat2": lat + dlat, "lon1": lon - dlon, "lon2": lon + dlon})
    comptes = dict(zip(df["type"], df["n"]))
    return {"velo": int(comptes.get("station_velo", 0)), "bus": int(comptes.get("arret_bus", 0))}


def dernier_km(distance_km, proches):
    """(mode, détail) du dernier kilomètre selon la distance gare → destination et ce qu'on trouve près de la gare."""
    if distance_km is None:
        return "--", "Pas de gare proche connue"
    if distance_km <= SEUIL_PIED_KM:
        return "Marche à pied", f"environ {max(1, round(distance_km * 1000 / VITESSE_MARCHE_M_MIN))} min à pied"
    pres = f"{proches['velo']} station(s) vélo et {proches['bus']} arrêt(s) de bus à moins de {int(RAYON_ALENTOURS_KM * 1000)} m de la gare"
    if distance_km <= SEUIL_VELO_BUS_KM and (proches["velo"] or proches["bus"]):
        return "Vélo / Bus", pres
    return "Voiture / Taxi", pres if distance_km <= SEUIL_VELO_BUS_KM else f"plus de {int(SEUIL_VELO_BUS_KM)} km de la gare"


def pois_autour(engine, lat, lon, categorie="tous", rayon_km=RAYON_POI_KM, limite=MAX_POI):
    """Lieux de la catégorie à moins de `rayon_km` d'une position, les plus proches d'abord, `limite` au plus par type :
    DataFrame id, type, nom, lat, lon, distance_km."""
    dlat, dlon = rayon_km / KM_PAR_DEGRE_LAT, rayon_km / (111.32 * math.cos(math.radians(lat)))
    df = pd.read_sql(sa.text(
        "SELECT id, type, nom, lat, lon FROM lieu WHERE type IN :types AND lat BETWEEN :lat1 AND :lat2 AND lon BETWEEN :lon1 AND :lon2").bindparams(
        sa.bindparam("types", expanding=True)),
        engine, params={"types": list(_types(categorie)), "lat1": lat - dlat, "lat2": lat + dlat, "lon1": lon - dlon, "lon2": lon + dlon})
    df["distance_km"] = ((df["lat"] - lat) * KM_PAR_DEGRE_LAT) ** 2 + ((df["lon"] - lon) * 111.32 * math.cos(math.radians(lat))) ** 2
    df["distance_km"] = df["distance_km"].pow(0.5)
    proches = df[df["distance_km"] <= rayon_km].sort_values("distance_km")
    return proches.groupby("type").head(limite).sort_values("distance_km").reset_index(drop=True)


def quand_depuis(date, heure=None, maintenant=None):
    """Date (« AAAA-MM-JJ ») et heure (« HH:MM ») du formulaire → datetime. Sans heure : maintenant si la date est aujourd'hui, sinon 8 h."""
    maintenant = maintenant or datetime.now()
    jour = datetime.strptime(str(date)[:10], "%Y-%m-%d").date()
    if heure:
        h, m = str(heure).split(":")
        return datetime.combine(jour, time(int(h), int(m)))
    return maintenant.replace(microsecond=0) if jour == maintenant.date() else datetime.combine(jour, HEURE_DEFAUT)


# Couleur proche de celle du service, et motif de trait différent (plein, tirets, pointillés) pour qu'on distingue les services sans les couleurs.
STYLES = {
    "inoui": ("TGV INOUI", "#9b0f5e", None),
    "ouigo": ("OUIGO", "#e6007e", "14 8"),
    "ter": ("TER / régional", "#0072b2", "6 6"),
    "intercites": ("Intercités", "#2e7d32", "14 6 2 6"),
    "rer": ("RER / Transilien", "#00a3a1", "3 5"),
    "bus": ("Car / bus", "#d55e00", "1 11"),
    "eurostar": ("Eurostar", "#00205b", "16 5 2 5 2 5"),
    "trenitalia": ("Trenitalia", "#d1232a", "16 5 2 5 2 5"),
    "renfe": ("Renfe AVE", "#7b3294", "16 5 2 5 2 5"),
    "international": ("International", "#4b3c8f", "16 5 2 5 2 5"),
    "inconnu": ("Train", "#555555", None),
    "pied": ("À pied", "#333333", "1 9"),
    "velo_bus": ("Vélo / Bus", "#e69f00", "10 7"),
    "voiture": ("Voiture / Taxi", "#555555", "18 8"),
}
DERNIER_KM = {"Marche à pied": "pied", "Vélo / Bus": "velo_bus", "Voiture / Taxi": "voiture"}


def style_ligne(section):
    """Style d'un train ou d'un car (une section Navitia) : {"cle", "libelle", "couleur", "tirets"}. tirets : motif Leaflet (« 14 8 »), None = trait plein."""
    mode = (section.get("mode_physique") or "").lower()
    texte = f"{section.get('ligne') or ''} {section.get('reseau') or ''}".lower()
    if any(m in mode for m in ("bus", "car", "navette")) or re.search(r"\b(car|bus|navette)\b", texte):
        cle = "bus"
    elif "ouigo" in texte:
        cle = "ouigo"
    elif "inoui" in texte or "tgv" in texte:
        cle = "inoui"
    elif "intercit" in texte:
        cle = "intercites"
    elif "eurostar" in texte:
        cle = "eurostar"
    elif "frecciarossa" in texte or "trenitalia" in texte:
        cle = "trenitalia"
    elif "renfe" in texte or re.search(r"\bave\b", texte):
        cle = "renfe"
    elif re.search(r"\b(db|ice|lyria|thalys)\b", texte):
        cle = "international"
    elif re.search(r"\b(rer|transilien|tramtrain)\b", texte):
        cle = "rer"
    elif section.get("ligne") or section.get("reseau"):
        cle = "ter"
    else:
        cle = "inconnu"
    libelle, couleur, tirets = STYLES[cle]
    return {"cle": cle, "libelle": libelle, "couleur": couleur, "tirets": tirets}


# Étiquettes des options d'un trajet, comme dans Waze : (texte, icône Font Awesome, couleur, valeur à minimiser).
CRITERES_ETIQUETTES = (
    ("Le plus rapide", "fa-bolt", "#0072b2", lambda t: t.get("duree_s")),
    ("Le plus écologique", "fa-leaf", "#2e7d32", lambda t: t.get("co2_g")),
    ("Le moins de correspondances", "fa-route", "#d55e00", lambda t: t.get("correspondances")),
)


def etiquettes_trajets(trajets):
    """Pour chaque trajet, la liste des étiquettes (texte, icône, couleur) qu'il mérite : le plus rapide, le plus écologique, le moins de correspondances.
    Une étiquette n'est donnée que si elle départage les options (si toutes sont à égalité, elle n'apprendrait rien) ; ex æquo : tous les meilleurs l'ont."""
    etiquettes = [[] for _ in trajets]
    if len(trajets) < 2:
        return etiquettes
    for texte, icone, couleur, valeur in CRITERES_ETIQUETTES:
        valeurs = [valeur(t) for t in trajets]
        connues = [v for v in valeurs if v is not None]
        if len(set(connues)) < 2:
            continue
        meilleur = min(connues)
        for i, v in enumerate(valeurs):
            if v == meilleur:
                etiquettes[i].append((texte, icone, couleur))
    return etiquettes


def style_dernier_km(mode):
    """Style du dernier kilomètre selon le mode conseillé (« Marche à pied », « Vélo / Bus », « Voiture / Taxi ») : petits points à pied, tirets en bus ou vélo."""
    cle = DERNIER_KM.get(mode, "pied")
    libelle, couleur, tirets = STYLES[cle]
    return {"cle": cle, "libelle": libelle, "couleur": couleur, "tirets": tirets}


def _horaires(s):
    """Gares, départ, arrivée (texte « AAAA-MM-JJ HH:MM:SS » : le dashboard les garde dans un dcc.Store) et retard en minutes d'une section."""
    return {"de": s.get("de"), "vers": s.get("vers"), "depart": str(s["depart"]) if s.get("depart") else None,
            "arrivee": str(s["arrivee"]) if s.get("arrivee") else None, "retard_min": s.get("retard_min") or 0}


def tracer_trajet(trajet, reseau, depart, arrivee):
    """Un dict par étape du trajet, dans l'ordre : points [[lat, lon], …], sur_voie, style (style_ligne), libelle (« TER 880693 »), marche (vrai à pied),
    de, vers (noms des gares), depart, arrivee, retard_min (voir lib/suivi.py : ils servent à placer le train).
    Les trains sont collés aux voies ; un car passe par la suite de ses arrêts (droit d'un arrêt au suivant, sans suivre la route) ;
    une correspondance à pied est un trait droit en petits points.
    `depart`, `arrivee` : (lon, lat) des gares, utilisées sans train pour tracer la liaison directe."""
    etapes = []
    for s in (trajet or {}).get("sections", []):
        if not (s.get("de_lonlat") and s.get("vers_lonlat")):
            continue
        de, vers = tuple(s["de_lonlat"]), tuple(s["vers_lonlat"])
        if s["type"] == "public_transport":
            style = style_ligne(s)
            if style["cle"] == "bus":            # un car ne roule pas sur les rails : on passe par chacun de ses arrêts
                points, ok = [tuple(a) for a in (s.get("arrets_lonlat") or [de, vers])], False
            else:
                points, ok = chemin(reseau, de, vers)
            etapes.append({**_horaires(s), "points": [[lat, lon] for lon, lat in points], "sur_voie": ok, "style": style, "marche": False,
                           "libelle": f"{s.get('ligne') or 'Train'} {s.get('numero') or ''}".strip()})
        elif s["type"] in ("transfer", "street_network", "crow_fly") and s.get("mode") == "walking" and s["duree_s"] >= 60 and de != vers:
            etapes.append({**_horaires(s), "points": [[de[1], de[0]], [vers[1], vers[0]]], "sur_voie": False, "style": style_dernier_km("Marche à pied"), "marche": True,
                           "libelle": f"À pied · {round(s['duree_s'] / 60)} min"})
    if not any(not e["marche"] for e in etapes):
        points, ok = chemin(reseau, depart, arrivee)
        etapes.insert(0, {"de": None, "vers": None, "depart": None, "arrivee": None, "retard_min": 0, "points": [[lat, lon] for lon, lat in points], "sur_voie": ok,
                          "style": style_ligne({}), "marche": False, "libelle": "Liaison directe"})
    return etapes


def rechercher(depart_id, destination_id, quand=None, retour=None, engine=None):
    """Prépare tout l'onglet pour un départ (id d'une gare) et une destination (id d'un lieu) : voir l'en-tête du module."""
    engine = engine or get_engine()
    depart, destination = _lieu(engine, depart_id), _lieu(engine, destination_id)
    if depart is None or destination is None:
        return None
    gare = _lieu(engine, destination["gare_proche_id"]) if destination["gare_proche_id"] else None
    distance = destination["distance_gare_km"]
    proches = alentours(engine, gare["lat"], gare["lon"]) if gare else {"velo": 0, "bus": 0}
    resultat = {"depart": depart, "destination": destination, "gare_arrivee": gare, "distance_km": distance, "alentours": proches,
                "dernier_km": dernier_km(distance, proches), "faisable": None if distance is None else distance <= SEUIL_VELO_BUS_KM,
                "trajets": [], "trajets_retour": [], "erreur_api": None, "meme_gare": gare is not None and gare["id"] == depart["id"],
                "pois": pois_autour(engine, destination["lat"], destination["lon"], "tous")}
    if gare is None or resultat["meme_gare"] or not depart["code_uic"] or not gare["code_uic"]:
        return resultat
    try:
        resultat["trajets"] = navitia.itineraires(navitia.id_gare(depart["code_uic"]), navitia.id_gare(gare["code_uic"]), quand=quand, nombre=MAX_TRAJETS)
        if retour is not None:
            resultat["trajets_retour"] = navitia.itineraires(navitia.id_gare(gare["code_uic"]), navitia.id_gare(depart["code_uic"]), quand=retour, nombre=MAX_TRAJETS)
    except RuntimeError as erreur:
        resultat["erreur_api"] = str(erreur)
    return resultat
