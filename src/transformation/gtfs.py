"""Transformation d'un GTFS (horaires théoriques d'un réseau) vers les tables reseau, ligne, circulation, calendrier, arret, passage.

Outils communs à tous les réseaux ; chaque réseau a son module (sncf.py…) qui dit où est son GTFS et comment reconnaître ses gares.
Identifiants préfixés par le réseau (« sncf:… ») pour rester uniques entre réseaux. Heures de passage en secondes depuis minuit
(plus de 86400 pour les trains de nuit).

Rattachement des arrêts : un arrêt dont le code UIC est celui d'une gare de la base pointe vers cette gare (arret.lieu_id). Les autres
reçoivent leur propre lieu (type « arret_bus » pour un car, `type_lieu` sinon : « arret_train » par défaut, « arret_bus » pour les réseaux urbains), avec leur gare la plus proche si elle est à moins de DISTANCE_GARE_MAX_KM (donc pas pour les arrêts à l'étranger).
Sans code UIC (réseaux étrangers, Île-de-France), `rayon_gare_m` permet de rattacher un arrêt par sa position : parmi les gares à moins de ce rayon,
la plus proche dont le nom est compatible (mot en commun), à défaut la plus proche si elle est à moins de DISTANCE_SANS_NOM_M mètres.
Seuls les arrêts desservis par au moins une circulation sont gardés (les zones d'arrêt qui ne servent qu'au regroupement sont donc écartées).
"""
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import sqlalchemy as sa
from pandas.api.types import union_categoricals
from scipy.spatial import cKDTree

from lib.db.connection import get_engine
from lib.db.models import Arret, Calendrier, Circulation, Gare, Ligne, Lieu, Passage, Reseau
from lieux import inserer, lignes_lieu, lire_gares, rattacher_aux_gares

DISTANCE_GARE_MAX_KM = 50          # au-delà, un arrêt n'a pas de gare « proche » (arrêts à l'étranger)
PAQUET_LECTURE = 1_000_000          # lignes de stop_times lues à la fois
PAQUET_TRANCHE = 100_000            # lignes converties et insérées à la fois
DISTANCE_SANS_NOM_M = 50          # sans nom compatible, un arrêt n'est rattaché à une gare que si elle est à moins de cette distance
MOTS_BANALS = {"gare", "saint", "sainte", "les", "des", "aeroport", "paris", "sncf", "rer"}
FICHIERS = ["routes", "trips", "stops"]
FICHIERS_FACULTATIFS = ["calendar", "calendar_dates"]      # selon les réseaux : jours par semaine, jours ajoutés ou retirés, ou les deux
JOURS_SEMAINE = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _csv(fichier):
    """Un fichier GTFS en texte, sans espaces parasites autour des noms de colonnes ni des valeurs (certains réseaux en laissent)."""
    df = pd.read_csv(fichier, dtype=str)
    df.columns = df.columns.str.strip()
    return df.apply(lambda colonne: colonne.str.strip())


def lire_passages(fichier, circulations=None):
    """stop_times.txt sous forme compacte : trip_id et stop_id en catégories, rang en entier, heures en secondes.
    Lu par paquets pour ne garder que les 5 colonnes utiles et, si `circulations` est donné, que celles-ci : un gros réseau
    (plus de 10 millions de passages) ne tient pas en mémoire en texte."""
    morceaux = []
    colonnes = ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"]
    for paquet in pd.read_csv(fichier, dtype=str, usecols=colonnes, chunksize=PAQUET_LECTURE, skipinitialspace=True):
        paquet.columns = paquet.columns.str.strip()
        if circulations is not None:
            paquet = paquet[paquet["trip_id"].isin(circulations)]
        morceaux.append(pd.DataFrame({
            "trip_id": paquet["trip_id"].astype("category"), "stop_id": paquet["stop_id"].astype("category"),
            "stop_sequence": pd.to_numeric(paquet["stop_sequence"], errors="coerce"),
            "heure_arrivee": en_secondes(paquet["arrival_time"]).astype("float32"),
            "heure_depart": en_secondes(paquet["departure_time"]).astype("float32"),
        }))
    if not morceaux:
        return pd.DataFrame({"trip_id": pd.Series(dtype="category"), "stop_id": pd.Series(dtype="category"), "stop_sequence": [],
                             "heure_arrivee": [], "heure_depart": []})
    tout = pd.concat([m.drop(columns=["trip_id", "stop_id"]) for m in morceaux], ignore_index=True)
    for colonne in ("trip_id", "stop_id"):
        tout[colonne] = pd.Series(union_categoricals([m[colonne].array for m in morceaux]))
    return tout


def lire(dossier, lignes=None):
    """Les fichiers du GTFS (les identifiants gardent leurs zéros). Retourne {nom: DataFrame} ; un fichier facultatif absent est vide.
    `lignes` : fonction qui, d'après le DataFrame des lignes, dit lesquelles garder (Series de booléens) ; les autres sont lues le moins possible."""
    brut = {nom: _csv(Path(dossier) / f"{nom}.txt") for nom in FICHIERS}
    for nom in FICHIERS_FACULTATIFS:
        fichier = Path(dossier) / f"{nom}.txt"
        brut[nom] = _csv(fichier) if fichier.is_file() else pd.DataFrame()
    if lignes is not None:
        brut["routes"] = brut["routes"][lignes(brut["routes"])]
        brut["trips"] = brut["trips"][brut["trips"]["route_id"].isin(brut["routes"]["route_id"])]
    brut["stop_times"] = lire_passages(Path(dossier) / "stop_times.txt", set(brut["trips"]["trip_id"]) if lignes is not None else None)
    return brut


def garder_lignes(brut, masque):
    """Le GTFS réduit aux lignes dont `masque` (Series de booléens sur brut["routes"]) est vrai : leurs circulations et passages seulement."""
    routes = brut["routes"][masque]
    trips = brut["trips"][brut["trips"]["route_id"].isin(routes["route_id"])]
    stop_times = brut["stop_times"][brut["stop_times"]["trip_id"].isin(trips["trip_id"])]
    return {**brut, "routes": routes, "trips": trips, "stop_times": stop_times}


def jours_de_circulation(brut):
    """DataFrame service_id, date : les jours de calendar.txt (jours de la semaine entre deux dates), plus les ajouts
    et moins les retraits de calendar_dates.txt (exception_type 1 et 2)."""
    morceaux = []
    cal = brut.get("calendar", pd.DataFrame())
    for ligne in cal.itertuples(index=False) if len(cal) else []:
        jours = pd.date_range(pd.to_datetime(ligne.start_date, format="%Y%m%d"), pd.to_datetime(ligne.end_date, format="%Y%m%d"))
        actifs = [getattr(ligne, nom) == "1" for nom in JOURS_SEMAINE]
        morceaux.append(pd.DataFrame({"service_id": ligne.service_id, "date": jours[[actifs[j.weekday()] for j in jours]]}))
    dates = brut.get("calendar_dates", pd.DataFrame())
    if len(dates):
        jour = pd.to_datetime(dates["date"], format="%Y%m%d")
        morceaux.append(pd.DataFrame({"service_id": dates["service_id"], "date": jour}).loc[dates["exception_type"] == "1"])
    base = pd.concat(morceaux, ignore_index=True).drop_duplicates() if morceaux else pd.DataFrame({"service_id": [], "date": []})
    if len(dates):
        retraits = pd.DataFrame({"service_id": dates["service_id"], "date": pd.to_datetime(dates["date"], format="%Y%m%d")}).loc[dates["exception_type"] == "2"]
        base = base.merge(retraits.assign(retire=True), how="left", on=["service_id", "date"])
        base = base[base["retire"].isna()].drop(columns="retire")
    return base.reset_index(drop=True)


def _col(df, nom):
    """Colonne facultative d'un fichier GTFS (vide si le réseau ne la fournit pas)."""
    return df[nom] if nom in df else pd.Series([None] * len(df), index=df.index, dtype=object)


def en_secondes(heures):
    """« 07:02:00 » → 25320 ; « 25:10:00 » (train de nuit) → 90600 ; vide ou illisible → NaN."""
    parts = heures.str.extract(r"^\s*(\d{1,3}):(\d{2}):(\d{2})\s*$").astype(float)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def normaliser(brut, reseau_id, uic=None, libelles=None, types_lignes=None):
    """Nettoie un GTFS. `uic` : Series code UIC par stop_id (None si l'arrêt n'est pas une gare connue) ;
    `libelles` : Series libellé par stop_id (« Train TER », « Car TER »…), qui donne aussi le type de chaque ligne ;
    `types_lignes` : {route_id: type} qui remplace ce type quand le réseau le connaît autrement.
    Retourne {lignes, circulations, calendrier, arrets, passages} ; arrets a lat, lon, uic et lieu_type en plus des colonnes de la table."""
    p = f"{reseau_id}:"
    stops = brut["stops"].copy()                                        # seuls ceux que les horaires desservent sont gardés plus bas
    stops["uic"] = stops["stop_id"].map(uic) if uic is not None else None
    stops["libelle"] = stops["stop_id"].map(libelles) if libelles is not None else None

    trips = brut["trips"]
    type_ligne = None
    if types_lignes is not None:
        type_ligne = pd.Series(types_lignes)
    elif libelles is not None:
        vus = brut["stop_times"][["trip_id", "stop_id"]].merge(trips[["trip_id", "route_id"]], on="trip_id")
        vus["libelle"] = vus["stop_id"].map(libelles)
        type_ligne = vus.dropna(subset=["libelle"]).groupby("route_id")["libelle"].agg(lambda s: s.mode().iloc[0])
    routes = brut["routes"]
    lignes = pd.DataFrame({
        "id": p + routes["route_id"], "reseau_id": reseau_id, "nom": _col(routes, "route_long_name").fillna(_col(routes, "route_short_name")),
        "type_transport": routes["route_id"].map(type_ligne) if type_ligne is not None else None,
        "couleur": ("#" + _col(routes, "route_color")).where(_col(routes, "route_color").notna()),
    })
    circulations = pd.DataFrame({
        "id": p + trips["trip_id"], "ligne_id": p + trips["route_id"], "service_id": p + trips["service_id"],
        "numero": _col(trips, "trip_short_name").fillna(_col(trips, "block_id")),
        "destination": _col(trips, "trip_headsign"),
    })
    jours = jours_de_circulation(brut)
    calendrier = pd.DataFrame({"service_id": p + jours["service_id"], "date": jours["date"].dt.date})
    calendrier = calendrier[calendrier["service_id"].isin(p + trips["service_id"])].drop_duplicates()
    st = brut["stop_times"]
    if "heure_arrivee" in st:                                                   # format compact de lire() : heures déjà en secondes
        passages = pd.DataFrame({
            "circulation_id": st["trip_id"].cat.rename_categories(lambda c: p + c), "ordre": st["stop_sequence"],
            "arret_id": st["stop_id"].cat.rename_categories(lambda c: p + c),
            "heure_arrivee": st["heure_arrivee"], "heure_depart": st["heure_depart"],
        })
    else:
        passages = pd.DataFrame({
            "circulation_id": p + st["trip_id"], "ordre": st["stop_sequence"].astype(int), "arret_id": p + st["stop_id"],
            "heure_arrivee": en_secondes(st["arrival_time"]), "heure_depart": en_secondes(st["departure_time"]),
        })
    passages = passages.dropna(subset=["ordre"])
    arrets = pd.DataFrame({
        "id": p + stops["stop_id"], "reseau_id": reseau_id, "nom": stops["stop_name"],
        "lat": pd.to_numeric(stops["stop_lat"], errors="coerce"), "lon": pd.to_numeric(stops["stop_lon"], errors="coerce"),
        "uic": stops["uic"], "libelle": stops["libelle"],
    })
    passages = passages.drop_duplicates(["circulation_id", "ordre"])            # clé de la table : un seul passage par rang dans une circulation
    arrets = arrets.drop_duplicates("id")
    arrets = arrets[arrets["id"].isin(set(passages["arret_id"]))].reset_index(drop=True)      # seuls les arrêts desservis
    passages = passages[passages["arret_id"].isin(set(arrets["id"]))]
    lignes, circulations = lignes.drop_duplicates("id"), circulations.drop_duplicates("id")
    circulations = circulations[circulations["ligne_id"].isin(set(lignes["id"]))]       # une circulation sans ligne connue n'a pas de sens
    passages = passages[passages["circulation_id"].isin(set(circulations["id"]))]
    return {"lignes": lignes, "circulations": circulations, "calendrier": calendrier, "arrets": arrets, "passages": passages}


def _entiers(df, colonnes):
    """Dicts prêts à insérer, avec les colonnes entières en int Python et NaN → None."""
    out = df.astype(object).where(df.notna(), None)
    for c in colonnes:
        out[c] = out[c].map(lambda v: None if v is None else int(v))
    return out.to_dict("records")


def _inserer_df(conn, modele, df, colonnes_entieres=()):
    """Insère un DataFrame par tranches : un gros réseau (millions de passages) ne tient pas en dicts Python d'un seul coup."""
    for debut in range(0, len(df), PAQUET_TRANCHE):
        conn.execute(sa.insert(modele), _entiers(df.iloc[debut:debut + PAQUET_TRANCHE], colonnes_entieres))


def mots(nom):
    """Mots significatifs d'un nom de gare ou d'arrêt (sans accents, majuscules ni mots banals) : « Paris Gare du Nord » → {nord}."""
    texte = unicodedata.normalize("NFD", str(nom).lower())
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return set(re.findall(r"[a-z0-9]{3,}", texte)) - MOTS_BANALS


def rattacher_par_position(arrets, gares, rayon_m):
    """Pour chaque arrêt (nom, lat, lon) l'id du lieu de la gare à rattacher, ou None. `gares` : id, nom, lat, lon.
    Parmi les gares à moins de `rayon_m`, la plus proche dont le nom est compatible ; à défaut la plus proche à moins de DISTANCE_SANS_NOM_M."""
    def plat(df):
        la, lo = df["lat"].to_numpy(float), df["lon"].to_numpy(float)
        return np.c_[lo * np.cos(np.radians(la)) * 111_320, la * 111_320]
    ids, noms = gares["id"].to_numpy(), [mots(n) for n in gares["nom"]]
    arbre = cKDTree(plat(gares))
    resultat = []
    for position, nom in zip(plat(arrets), arrets["nom"]):
        voisines = sorted(arbre.query_ball_point(position, rayon_m), key=lambda k: np.hypot(*(arbre.data[k] - position)))
        compatible = next((k for k in voisines if mots(nom) & noms[k]), None)
        proche = voisines[0] if voisines and np.hypot(*(arbre.data[voisines[0]] - position)) <= DISTANCE_SANS_NOM_M else None
        choix = compatible if compatible is not None else proche
        resultat.append(None if choix is None else int(ids[choix]))
    return resultat


def charger(frames, reseau, source, engine=None, rayon_gare_m=None, type_lieu="arret_train"):
    """Remplace en une transaction tout le réseau : reseau (dict id, nom, mode), lignes, circulations, calendrier, arrêts, passages
    et les lieux d'arrêts créés pour lui. Retourne le nombre de lignes, circulations, arrêts et passages chargés."""
    engine = engine or get_engine()
    rid = reseau["id"]
    gares = lire_gares(engine)
    arrets = frames["arrets"].copy()
    with engine.begin() as conn:
        lieux_arrets = sa.select(Lieu.id).where(Lieu.type.in_(["arret_bus", "arret_train"]), Lieu.source == source)
        circulations = sa.select(Circulation.id).join(Ligne, Ligne.id == Circulation.ligne_id).where(Ligne.reseau_id == rid)
        conn.execute(sa.delete(Passage).where(Passage.circulation_id.in_(circulations)))
        conn.execute(sa.delete(Calendrier).where(Calendrier.service_id.like(f"{rid}:%")))
        conn.execute(sa.delete(Circulation).where(Circulation.id.in_(circulations)))
        conn.execute(sa.delete(Arret).where(Arret.reseau_id == rid))
        conn.execute(sa.delete(Lieu).where(Lieu.id.in_(lieux_arrets)))
        conn.execute(sa.delete(Ligne).where(Ligne.reseau_id == rid))
        conn.execute(sa.delete(Reseau).where(Reseau.id == rid))

        gare_par_uic = dict(conn.execute(sa.select(Gare.code_uic, Gare.lieu_id)).all())
        arrets["lieu_id"] = arrets["uic"].map(gare_par_uic)
        if rayon_gare_m and len(gares):
            libres = arrets[arrets["lieu_id"].isna() & arrets["lat"].notna() & arrets["lon"].notna()]
            noms = pd.DataFrame(conn.execute(sa.select(Lieu.id, Lieu.nom, Lieu.lat, Lieu.lon).where(Lieu.type == "gare")).all(),
                                columns=["id", "nom", "lat", "lon"]).dropna(subset=["lat", "lon"])
            arrets["lieu_id"] = arrets["lieu_id"].astype(object)     # colonne de décimaux (NaN) : pandas 2.3+ refuse d'y écrire des identifiants
            arrets.loc[libres.index, "lieu_id"] = pd.Series(rattacher_par_position(libres, noms, rayon_gare_m), index=libres.index, dtype=object)
        nouveaux = arrets[arrets["lieu_id"].isna() & arrets["lat"].notna() & arrets["lon"].notna()].copy()
        nouveaux["type"] = nouveaux["libelle"].fillna("").str.startswith("Car").map({True: "arret_bus", False: type_lieu})
        premier = (conn.scalar(sa.select(sa.func.max(Lieu.id))) or 0) + 1
        nouveaux["lieu_id"] = range(premier, premier + len(nouveaux))
        lieux = rattacher_aux_gares(nouveaux[["nom", "lat", "lon"]], gares).assign(id=nouveaux["lieu_id"].to_numpy())
        trop_loin = lieux["distance_gare_km"].isna() | (lieux["distance_gare_km"] > DISTANCE_GARE_MAX_KM)
        lieux.loc[trop_loin, ["gare_proche_id", "distance_gare_km"]] = None
        lignes_lieux = lignes_lieu(lieux, None, source)
        for ligne, type_ in zip(lignes_lieux, nouveaux["type"]):
            ligne["type"] = type_
        arrets.loc[nouveaux.index, "lieu_id"] = nouveaux["lieu_id"]

        conn.execute(sa.insert(Reseau), [{**reseau, "source": source}])
        inserer(conn, Lieu, lignes_lieux)
        _inserer_df(conn, Ligne, frames["lignes"])
        _inserer_df(conn, Arret, arrets[["id", "reseau_id", "lieu_id", "nom"]], ["lieu_id"])
        _inserer_df(conn, Circulation, frames["circulations"])
        _inserer_df(conn, Calendrier, frames["calendrier"])
        _inserer_df(conn, Passage, frames["passages"], ["ordre", "heure_arrivee", "heure_depart"])
    return len(frames["lignes"]), len(frames["circulations"]), len(arrets), len(frames["passages"])
