#!/usr/bin/env python3
"""
navitia_extract.py - Extraction des données SNCF via Navitia pour "MySNCF Experience".

Étapes (--steps, séparées par des virgules) :
  catalog      référentiels : coverage, datasets, contributors, networks, companies, modes, lines, routes, poi_types
  gares        stop_areas (gares) + typologie (physical_modes / commercial_modes) + région/UIC
  gares_pt     pt-ref par gare : nb de lignes / routes / réseaux / quais (stop_points) / accessibilité
  velo         intermodalité (KPI 2) : nb de locations / stationnements vélo autour de chaque gare
  intermodal   intermodalité hors vélo : parkings, taxis, autopartage, bus... + gares voisines (maillage)
  isochrones   zones de chalandise 5/10/15 min à pied et à vélo par gare (KPI 1 et 3)
  reach_pt     isochrones AVEC transports en commun (1 h / 2 h) : rayonnement de chaque gare
  departures   nb de départs sur une journée type par gare (niveau de desserte)
  service      amplitude de service : premier/dernier départ et arrivée par gare (excursion à la journée)
  directs      destinations accessibles sans correspondance depuis chaque gare (route_schedules)
  disruptions  perturbations en cours / à venir sur le coverage (/disruptions)
  journeys     trajets directs (sans transport en commun) gare -> POI, sur un fichier de POI (optionnel)

Usage :
  export NAVITIA_TOKEN="ton-token"
  python lib/navitia_extract.py --steps catalog,gares --limit 20     # petit test
  python lib/navitia_extract.py                                       # extraction complète
  python lib/navitia_extract.py --steps journeys --poi-csv pois.csv --max-pairs 200

Tout appel est mis en cache dans data/raw/navitia/_cache : relancer le script reprend
là où il s'est arrêté et ne consomme pas de quota pour les requêtes déjà faites.
"""
import argparse
import hashlib
import json
import logging
import os
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://api.navitia.io/v1"
COVERAGE = "sncf"
OUT = Path("data/raw/navitia")
CACHE = OUT / "_cache"

# Familles de modes considérées comme "gare ferroviaire voyageurs"
TRAIN_MODES = {
    "physical_mode:Train",
    "physical_mode:LongDistanceTrain",
    "physical_mode:LocalTrain",
    "physical_mode:RapidTransit",
}

# Hypothèses du cadrage : 15 min à pied = 1 km ; 15 min à vélo = 5 km
MAX_S = 900
MODES = {
    "walking": {"speed_param": "walking_speed", "speed": 1.11},  # m/s (~4 km/h)
    "bike": {"speed_param": "bike_speed", "speed": 5.56},        # m/s (~20 km/h)
}

# Types de POI OSM utiles pour l'intermodalité vélo (vérifiés via /poi_types à l'étape catalog)
BIKE_POI_TYPES = {
    "bike_rental": "poi_type:amenity:bicycle_rental",
    "bike_parking": "poi_type:amenity:bicycle_parking",
}

# Autres POI d'intermodalité (voiture, taxi, autopartage, bus) - étape 'intermodal'
OTHER_POI_TYPES = {
    "parking": "poi_type:amenity:parking",
    "taxi": "poi_type:amenity:taxi",
    "car_sharing": "poi_type:amenity:car_sharing",
    "bus_station": "poi_type:amenity:bus_station",
    "bike_repair": "poi_type:amenity:bicycle_repair_station",
}

log = logging.getLogger("navitia")


# --------------------------------------------------------------------------- client
class Navitia:
    def __init__(self, token, coverage=COVERAGE, pause=0.1):
        self.coverage = coverage
        self.pause = pause
        self.s = requests.Session()
        self.s.headers["Authorization"] = token
        retry = Retry(
            total=5,
            backoff_factor=1.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            respect_retry_after_header=True,
        )
        self.s.mount("https://", HTTPAdapter(max_retries=retry))
        CACHE.mkdir(parents=True, exist_ok=True)
        self.n_calls = 0

    def get(self, path, params=None):
        """GET /coverage/{coverage}/{path}. Retourne le JSON, avec '_http_status' ajouté.
        Les réponses 200 et 404 (définitives) sont mises en cache."""
        url = f"{BASE}/coverage/{self.coverage}/{path.lstrip('/')}"
        key = hashlib.sha1(
            (url + json.dumps(params, sort_keys=True, default=str)).encode()
        ).hexdigest()
        cache_file = CACHE / f"{key}.json"
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))

        try:
            r = self.s.get(url, params=params, timeout=30)
        except requests.RequestException as e:
            log.warning("Erreur réseau sur %s : %s", path, e)
            return {"_http_status": 0, "error": {"message": str(e)}}
        self.n_calls += 1
        time.sleep(self.pause)

        if r.status_code == 401:
            raise SystemExit("401 Unauthorized : vérifie NAVITIA_TOKEN.")
        try:
            body = r.json()
        except ValueError:
            body = {}
        body["_http_status"] = r.status_code
        if r.status_code in (200, 404):
            cache_file.write_text(json.dumps(body), encoding="utf-8")
        else:
            log.warning("HTTP %s sur %s", r.status_code, path)
        return body

    def paginate(self, path, key, params=None, count=200):
        """Parcourt toutes les pages d'une collection (max 200 objets par page)."""
        params = dict(params or {})
        params["count"] = count
        rows, page = [], 0
        while True:
            params["start_page"] = page
            data = self.get(path, params)
            items = data.get(key, [])
            rows.extend(items)
            total = data.get("pagination", {}).get("total_result", 0)
            page += 1
            if not items or len(rows) >= total:
                break
        return rows

    def total(self, path, params=None):
        """Nombre total de résultats d'une requête (count=1, on ne lit que la pagination)."""
        p = dict(params or {})
        p["count"] = 1
        data = self.get(path, p)
        if data.get("_http_status") != 200:
            return None
        return data.get("pagination", {}).get("total_result", 0)

    def first_last(self, path, key, params):
        """Premier et dernier élément d'une liste triée (2 appels : count=1 page 0, puis page total-1)."""
        p = {**params, "count": 1, "start_page": 0}
        data = self.get(path, p)
        if data.get("_http_status") != 200:
            return None, None, None
        total = data.get("pagination", {}).get("total_result", 0)
        first = (data.get(key) or [None])[0]
        if total <= 1:
            return first, first, total
        last_page = self.get(path, {**params, "count": 1, "start_page": total - 1})
        last = (last_page.get(key) or [None])[0]
        return first, last, total


# --------------------------------------------------------------------------- utilitaires
def haversine_m(lon1, lat1, lon2, lat2):
    """Distance à vol d'oiseau en mètres (vectorisée)."""
    r = 6371008.8
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def save_json(obj, name):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def save_csv(df, name):
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / name, index=False, encoding="utf-8")
    log.info("-> %s (%d lignes)", OUT / name, len(df))


def load_gares(only_train=True, limit=None):
    f = OUT / "gares.csv"
    if not f.exists():
        raise SystemExit("gares.csv introuvable : lance d'abord l'étape 'gares'.")
    df = pd.read_csv(f, dtype={"uic": "string"})
    if only_train:
        df = df[df["is_train"]]
    return df.head(limit) if limit else df


def coord_param(lon, lat):
    return f"{lon};{lat}"


def next_weekday(weekday=1):  # 0=lundi, 1=mardi...
    d = date.today() + timedelta(days=1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


def type_day(args):
    """Journée type (--date, sinon prochain mardi)."""
    return date.fromisoformat(args.date) if args.date else next_weekday(1)


def nav_dt(value):
    """'20261006T081500' -> '2026-10-06T08:15:00' (None si vide)."""
    if not value:
        return None
    return pd.to_datetime(value, format="%Y%m%dT%H%M%S", errors="coerce").isoformat()


BASE_PT = {"disable_geojson": "true", "disable_disruption": "true"}


# --------------------------------------------------------------------------- étape catalog
def step_catalog(nav, args):
    cov = nav.get("")  # /coverage/sncf
    save_json(cov, "coverage.json")
    region = (cov.get("regions") or [{}])[0]
    log.info(
        "Coverage %s : statut=%s, production %s -> %s",
        region.get("id"), region.get("status"),
        region.get("start_production_date"), region.get("end_production_date"),
    )

    for coll in ("datasets", "contributors", "networks", "companies", "physical_modes",
                 "commercial_modes", "poi_types"):
        rows = nav.paginate(coll, coll)
        save_json(rows, f"{coll}.json")
        if rows:
            save_csv(pd.json_normalize(rows), f"ref_{coll}.csv")

    lines = nav.paginate("lines", "lines", BASE_PT)
    flat = [
        {
            "line_id": l.get("id"),
            "code": l.get("code"),
            "name": l.get("name"),
            "network_id": (l.get("network") or {}).get("id"),
            "network": (l.get("network") or {}).get("name"),
            "commercial_mode": (l.get("commercial_mode") or {}).get("name"),
            "physical_modes": "|".join(m.get("id", "") for m in l.get("physical_modes", [])),
        }
        for l in lines
    ]
    save_csv(pd.DataFrame(flat), "lines.csv")

    # routes = une direction d'une ligne (terminus), utile pour typer les dessertes
    routes = nav.paginate("routes", "routes", BASE_PT)
    save_csv(pd.DataFrame([
        {
            "route_id": r.get("id"),
            "name": r.get("name"),
            "line_id": (r.get("line") or {}).get("id"),
            "direction_id": (r.get("direction") or {}).get("id"),
            "direction": (r.get("direction") or {}).get("name"),
        }
        for r in routes
    ]), "routes.csv")

    poi_ids = {p.get("id") for p in json.loads((OUT / "poi_types.json").read_text())} \
        if (OUT / "poi_types.json").exists() else set()
    for name, pid in {**BIKE_POI_TYPES, **OTHER_POI_TYPES}.items():
        if pid not in poi_ids:
            log.warning("poi_type %s absent de la coverage : l'étape correspondante donnera 0/None.", pid)


# --------------------------------------------------------------------------- étape gares
def _admin(sa, level):
    for a in sa.get("administrative_regions") or []:
        if a.get("level") == level:
            return a
    return {}


def flatten_stop_area(sa):
    coord = sa.get("coord") or {}
    codes = sa.get("codes") or []
    uic = next((c.get("value") for c in codes if "uic" in str(c.get("type", "")).lower()), None)
    return {
        "stop_area_id": sa.get("id"),
        "name": sa.get("name"),
        "lon": float(coord["lon"]) if coord.get("lon") else None,
        "lat": float(coord["lat"]) if coord.get("lat") else None,
        "uic": uic,
        "commune": _admin(sa, 8).get("name"),
        "insee": _admin(sa, 8).get("insee"),
        "departement": _admin(sa, 6).get("name"),
        "region": _admin(sa, 4).get("name"),
        "codes_json": json.dumps(codes, ensure_ascii=False),
    }


def step_gares(nav, args):
    base = BASE_PT
    sas = nav.paginate("stop_areas", "stop_areas", base)
    df = pd.DataFrame([flatten_stop_area(s) for s in sas]).dropna(subset=["lon", "lat"])
    log.info("%d stop_areas récupérés", len(df))

    # Typologie : quels modes desservent quelle gare ?
    for kind, label in (("physical_modes", "physical_modes"), ("commercial_modes", "commercial_modes")):
        ref = json.loads((OUT / f"{kind}.json").read_text()) if (OUT / f"{kind}.json").exists() \
            else nav.paginate(kind, kind)
        tag = {}
        for m in ref:
            mid = m.get("id")
            ids = [s["id"] for s in nav.paginate(f"{kind}/{mid}/stop_areas", "stop_areas",
                                                  {**base, "depth": 0})]
            for sid in ids:
                tag.setdefault(sid, []).append(mid)
            log.info("%s : %d gares", mid, len(ids))
        df[label] = df["stop_area_id"].map(lambda i: "|".join(sorted(tag.get(i, []))))

    df["is_train"] = df["physical_modes"].map(lambda s: bool(TRAIN_MODES & set(s.split("|"))))
    df["has_tgv_like"] = df["physical_modes"].str.contains("LongDistanceTrain")
    df["has_ter_like"] = df["physical_modes"].str.contains("LocalTrain")
    if args.limit:
        log.info("--limit ignoré à cette étape : on garde toutes les gares.")
    save_csv(df, "gares.csv")
    log.info("dont %d gares ferroviaires (is_train)", int(df["is_train"].sum()))


# --------------------------------------------------------------------------- étape gares_pt
def step_gares_pt(nav, args):
    """pt-ref par gare : lignes, routes, réseaux et quais (stop_points) qui desservent la gare."""
    gares = load_gares(limit=args.limit)
    rows = []
    for i, g in enumerate(gares.itertuples(), 1):
        sid = g.stop_area_id
        lines = nav.paginate(f"stop_areas/{sid}/lines", "lines", {**BASE_PT, "depth": 1})
        sa = nav.get(f"stop_areas/{sid}", {**BASE_PT, "depth": 1})
        sps = ((sa.get("stop_areas") or [{}])[0]).get("stop_points") or []
        eq = [set((sp.get("equipments") or [])) for sp in sps]
        rows.append({
            "stop_area_id": sid,
            "n_lines": len(lines),
            "n_routes": nav.total(f"stop_areas/{sid}/routes", BASE_PT),
            "n_networks": nav.total(f"stop_areas/{sid}/networks", BASE_PT),
            "n_stop_points": len(sps),
            "n_wheelchair_sp": sum("has_wheelchair_boarding" in e for e in eq),
            "n_bike_accepted_sp": sum("has_bike_accepted" in e for e in eq),
            "lines": "|".join(sorted(l.get("code") or l.get("name") or "" for l in lines)),
        })
        if i % 100 == 0:
            log.info("gares_pt : %d/%d gares (%d appels)", i, len(gares), nav.n_calls)
    save_csv(pd.DataFrame(rows), "gares_pt.csv")


# --------------------------------------------------------------------------- étapes velo / intermodal
def _count_poi_nearby(nav, gares, poi_types, distances, label):
    rows = []
    for i, g in enumerate(gares.itertuples(), 1):
        row = {"stop_area_id": g.stop_area_id}
        for name, pid in poi_types.items():
            for dist in distances:
                row[f"n_{name}_{dist}m"] = nav.total(
                    f"stop_areas/{g.stop_area_id}/places_nearby",
                    {"type[]": ["poi"], "distance": dist, "filter": f"poi_type.id={pid}",
                     "add_poi_infos[]": ["none"], **BASE_PT},
                )
        rows.append(row)
        if i % 100 == 0:
            log.info("%s : %d/%d gares (%d appels)", label, i, len(gares), nav.n_calls)
    return pd.DataFrame(rows)


def step_velo(nav, args):
    gares = load_gares(limit=args.limit)
    save_csv(_count_poi_nearby(nav, gares, BIKE_POI_TYPES, (200, 500, 1000), "velo"), "gares_velo.csv")


def step_intermodal(nav, args):
    """Autres POI d'intermodalité + nombre de gares voisines (maillage ferroviaire local)."""
    gares = load_gares(limit=args.limit)
    df = _count_poi_nearby(nav, gares, OTHER_POI_TYPES, (200, 500, 1000), "intermodal")
    for dist in (5000, 10000):
        df[f"n_stop_areas_{dist}m"] = [
            nav.total(f"stop_areas/{sid}/places_nearby",
                      {"type[]": ["stop_area"], "distance": dist, **BASE_PT})
            for sid in df["stop_area_id"]
        ]
    save_csv(df, "gares_intermodal.csv")


# --------------------------------------------------------------------------- étapes isochrones / reach_pt
def _isochrone_features(nav, gares, mode_cfgs, durations, with_pt, physical, from_datetime=None):
    """Une requête /isochrones par gare et par mode.
    with_pt=False : on interdit tous les modes de transport en commun (forbidden_uris[]) pour
    obtenir la zone atteignable uniquement à pied / à vélo depuis la gare ('dernier kilomètre')."""
    feats = {m: [] for m in mode_cfgs}
    for i, g in enumerate(gares.itertuples(), 1):
        for mode, cfg in mode_cfgs.items():
            params = {
                "from": coord_param(g.lon, g.lat),
                "boundary_duration[]": durations,
                "first_section_mode[]": [mode],
                "disable_geojson": "false",
            }
            if cfg.get("speed_param"):
                params[cfg["speed_param"]] = cfg["speed"]
            if not with_pt:
                params["forbidden_uris[]"] = physical
            if from_datetime:
                params["datetime"] = from_datetime
                params["data_freshness"] = "base_schedule"
            data = nav.get("isochrones", params)
            if data.get("_http_status") != 200:
                continue
            for iso in data.get("isochrones", []):
                geom = iso.get("geojson")
                if geom and geom.get("type") == "Feature":
                    geom = geom.get("geometry")
                if not geom or not geom.get("coordinates"):
                    continue
                feats[mode].append({
                    "type": "Feature",
                    "geometry": geom,
                    "properties": {
                        "stop_area_id": g.stop_area_id,
                        "name": g.name,
                        "mode": mode,
                        "max_duration_s": iso.get("max_duration"),
                        "min_duration_s": iso.get("min_duration"),
                        "with_pt": with_pt,
                    },
                })
        if i % 50 == 0:
            log.info("isochrones : %d/%d gares (%d appels)", i, len(gares), nav.n_calls)
    return feats


def _physical_modes():
    f = OUT / "physical_modes.json"
    return [m["id"] for m in json.loads(f.read_text())] if f.exists() else []


def step_isochrones(nav, args):
    gares = load_gares(limit=args.limit)
    durations = [int(d) for d in args.durations.split(",")]
    feats = _isochrone_features(nav, gares, MODES, durations, args.isochrone_pt == "pt",
                                _physical_modes())
    for mode, fl in feats.items():
        save_json({"type": "FeatureCollection", "features": fl}, f"isochrones_{mode}.geojson")
        log.info("isochrones_%s.geojson : %d polygones", mode, len(fl))


def step_reach_pt(nav, args):
    """Rayonnement en transports en commun depuis chaque gare (journée type, départ --reach-hour)."""
    gares = load_gares(limit=args.limit)
    durations = [int(d) for d in args.reach_durations.split(",")]
    dt = type_day(args).strftime("%Y%m%dT") + f"{args.reach_hour:02d}0000"
    feats = _isochrone_features(nav, gares, {"walking": {}}, durations, True, [], from_datetime=dt)
    fl = feats["walking"]
    save_json({"type": "FeatureCollection", "features": fl}, "isochrones_pt.geojson")
    log.info("isochrones_pt.geojson : %d polygones", len(fl))


# --------------------------------------------------------------------------- étapes departures / service
def step_departures(nav, args):
    day = type_day(args)
    from_dt = day.strftime("%Y%m%dT000000")
    gares = load_gares(limit=args.limit)
    rows = []
    for i, g in enumerate(gares.itertuples(), 1):
        data = nav.get(
            f"stop_areas/{g.stop_area_id}/departures",
            {"from_datetime": from_dt, "duration": 86400, "count": 200,
             "data_freshness": "base_schedule", "depth": 0, **BASE_PT},
        )
        if data.get("_http_status") == 200:
            total = data.get("pagination", {}).get("total_result")
            n = total if total is not None else len(data.get("departures", []))
        else:
            n = None
        rows.append({"stop_area_id": g.stop_area_id, "date": day.isoformat(), "n_departures_24h": n})
        if i % 100 == 0:
            log.info("departures : %d/%d gares (%d appels)", i, len(gares), nav.n_calls)
    save_csv(pd.DataFrame(rows), "gares_departures.csv")


def step_service(nav, args):
    """Amplitude de service d'une gare sur la journée type : premier/dernier départ et arrivée
    (2 appels par sens). Sert à mesurer le potentiel d'excursion à la journée."""
    day = type_day(args)
    params = {"from_datetime": day.strftime("%Y%m%dT000000"), "duration": 86400,
              "data_freshness": "base_schedule", "depth": 0, **BASE_PT}
    gares = load_gares(limit=args.limit)
    rows = []
    for i, g in enumerate(gares.itertuples(), 1):
        row = {"stop_area_id": g.stop_area_id, "date": day.isoformat()}
        for kind, key, field in (("departures", "departures", "departure_date_time"),
                                 ("arrivals", "arrivals", "arrival_date_time")):
            first, last, total = nav.first_last(f"stop_areas/{g.stop_area_id}/{kind}", key, params)
            sdt = lambda x: ((x or {}).get("stop_date_time") or {}).get(field)
            row[f"n_{kind}_24h"] = total
            row[f"first_{kind[:-1]}"] = nav_dt(sdt(first))
            row[f"last_{kind[:-1]}"] = nav_dt(sdt(last))
        rows.append(row)
        if i % 100 == 0:
            log.info("service : %d/%d gares (%d appels)", i, len(gares), nav.n_calls)
    df = pd.DataFrame(rows)
    # Fenêtre d'excursion : premier train du matin -> dernier retour du soir
    first_dep = pd.to_datetime(df["first_departure"], errors="coerce")
    last_arr = pd.to_datetime(df["last_arrival"], errors="coerce")
    df["span_h"] = ((last_arr - first_dep).dt.total_seconds() / 3600).round(1)
    save_csv(df, "gares_service.csv")


# --------------------------------------------------------------------------- étape directs
def step_directs(nav, args):
    """Destinations accessibles SANS correspondance depuis chaque gare.
    /stop_areas/{id}/route_schedules renvoie, par route, la table des arrêts dans l'ordre de
    desserte : les arrêts situés après la gare d'origine sont ses destinations directes."""
    day = type_day(args)
    params = {"from_datetime": day.strftime("%Y%m%dT000000"), "duration": 86400,
              "items_per_schedule": 1, "data_freshness": "base_schedule", "depth": 2, **BASE_PT}
    gares = load_gares(limit=args.limit)
    rows, summary = [], []
    for i, g in enumerate(gares.itertuples(), 1):
        origin = g.stop_area_id
        schedules = nav.paginate(f"stop_areas/{origin}/route_schedules", "route_schedules", params)
        dests = set()
        for rs in schedules:
            di = rs.get("display_informations") or {}
            stops = [
                ((r.get("stop_point") or {}).get("stop_area") or {}) for r in
                (rs.get("table") or {}).get("rows", [])
            ]
            ids = [s.get("id") for s in stops]
            if origin not in ids:
                continue
            for rank, s in enumerate(stops[ids.index(origin) + 1:], 1):
                if not s.get("id"):
                    continue
                dests.add(s["id"])
                rows.append({
                    "origin_id": origin, "dest_id": s["id"], "dest_name": s.get("name"),
                    "line": di.get("code"), "network": di.get("network"),
                    "commercial_mode": di.get("commercial_mode"),
                    "direction": di.get("direction"), "n_stops_away": rank,
                })
        summary.append({"stop_area_id": origin, "n_routes": len(schedules),
                        "n_direct_destinations": len(dests)})
        if i % 50 == 0:
            log.info("directs : %d/%d gares (%d appels)", i, len(gares), nav.n_calls)
    save_csv(pd.DataFrame(rows).drop_duplicates(), "gares_directs.csv")
    save_csv(pd.DataFrame(summary), "gares_directs_summary.csv")


# --------------------------------------------------------------------------- étape disruptions
def step_disruptions(nav, args):
    """Perturbations du coverage (travaux, suppressions, retards annoncés)."""
    rows = []
    for d in nav.paginate("disruptions", "disruptions", {"depth": 0}):
        periods = d.get("application_periods") or []
        objs = d.get("impacted_objects") or []
        rows.append({
            "disruption_id": d.get("id"),
            "status": d.get("status"),
            "cause": d.get("cause"),
            "category": d.get("category"),
            "severity": (d.get("severity") or {}).get("name"),
            "effect": (d.get("severity") or {}).get("effect"),
            "begin": nav_dt(periods[0].get("begin")) if periods else None,
            "end": nav_dt(periods[-1].get("end")) if periods else None,
            "n_impacted": len(objs),
            "impacted_ids": "|".join(
                (o.get("pt_object") or {}).get("id", "") for o in objs),
        })
    save_csv(pd.DataFrame(rows), "disruptions.csv")


# --------------------------------------------------------------------------- étape journeys
def direct_path_kpi(nav, origin, dest, mode="walking"):
    """Version corrigée de get_journey_kpi : durée et distance d'un trajet DIRECT
    (sans transport en commun) entre deux points 'lon;lat'.

    Différences avec le script de départ :
    - direct_path=only : sans ça Navitia peut renvoyer un trajet en train et la durée n'a
      plus rien à voir avec "à pied / à vélo depuis la gare" ;
    - la distance vient de sections[].path[].length (les sections n'ont pas de champ 'length') ;
    - la vitesse est alignée sur le cadrage (1 km en 15 min à pied, 5 km en 15 min à vélo)."""
    cfg = MODES[mode]
    params = {
        "from": origin, "to": dest,
        "first_section_mode[]": [mode], "last_section_mode[]": [mode],
        "direct_path": "only", "direct_path_mode[]": [mode],
        cfg["speed_param"]: cfg["speed"],
        "disable_geojson": "true",
    }
    data = nav.get("journeys", params)
    status = data.get("_http_status")
    journeys = data.get("journeys") or []
    if status in (404, 200) and not journeys:
        return {"status": "NO_JOURNEY", "duration_min": None, "distance_m": None}
    if status != 200:
        return {"status": f"ERROR_{status}", "duration_min": None, "distance_m": None}
    best = journeys[0]
    dist = sum(
        item.get("length", 0)
        for s in best.get("sections", []) if s.get("type") == "street_network"
        for item in s.get("path", [])
    )
    if not dist:
        dist = (best.get("distances") or {}).get(mode)
    return {"status": "OK", "duration_min": round(best.get("duration", 0) / 60, 1), "distance_m": dist}


def step_journeys(nav, args):
    if not args.poi_csv:
        raise SystemExit("--poi-csv requis (colonnes : poi_id, lon, lat, categorie).")
    gares = load_gares().reset_index(drop=True)
    pois = pd.read_csv(args.poi_csv)
    if args.max_pairs:
        pois = pois.sample(min(len(pois), args.max_pairs), random_state=0)
    glon, glat = gares["lon"].to_numpy(), gares["lat"].to_numpy()

    rows = []
    for p in pois.itertuples():
        d = haversine_m(p.lon, p.lat, glon, glat)
        for gi in np.argsort(d)[: args.nearest]:
            g = gares.iloc[gi]
            for mode, cfg in MODES.items():
                # Pré-filtre : un trajet est toujours plus long que la distance à vol d'oiseau
                if d[gi] > cfg["speed"] * MAX_S:
                    continue
                kpi = direct_path_kpi(nav, coord_param(g.lon, g.lat), coord_param(p.lon, p.lat), mode)
                rows.append({
                    "poi_id": p.poi_id, "categorie": getattr(p, "categorie", None),
                    "stop_area_id": g.stop_area_id, "mode": mode,
                    "crowfly_m": round(float(d[gi])), **kpi,
                    "within_15min": kpi["duration_min"] is not None and kpi["duration_min"] <= MAX_S / 60,
                })
    save_csv(pd.DataFrame(rows), "journeys_gare_poi.csv")


# --------------------------------------------------------------------------- main
STEPS = {
    "catalog": step_catalog,
    "gares": step_gares,
    "gares_pt": step_gares_pt,
    "velo": step_velo,
    "intermodal": step_intermodal,
    "isochrones": step_isochrones,
    "reach_pt": step_reach_pt,
    "departures": step_departures,
    "service": step_service,
    "directs": step_directs,
    "disruptions": step_disruptions,
    "journeys": step_journeys,
}

# Étapes lancées par défaut (reach_pt et journeys sont coûteuses / optionnelles : à demander via --steps)
DEFAULT_STEPS = "catalog,gares,gares_pt,velo,intermodal,isochrones,departures,service,directs,disruptions"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--steps", default=DEFAULT_STEPS)
    ap.add_argument("--limit", type=int, help="ne traiter que N gares (tests)")
    ap.add_argument("--durations", default="300,600,900", help="isochrones, en secondes")
    ap.add_argument("--isochrone-pt", choices=["nopt", "pt"], default="nopt",
                    help="nopt = marche/vélo seuls (défaut) ; pt = avec transports en commun")
    ap.add_argument("--reach-durations", default="3600,7200", help="reach_pt, en secondes")
    ap.add_argument("--reach-hour", type=int, default=8, help="reach_pt : heure de départ (défaut 8h)")
    ap.add_argument("--date", help="journée type (YYYY-MM-DD), défaut : prochain mardi")
    ap.add_argument("--poi-csv", help="CSV de POI pour l'étape journeys")
    ap.add_argument("--max-pairs", type=int, help="échantillon de POI pour l'étape journeys")
    ap.add_argument("--nearest", type=int, default=2, help="nb de gares les plus proches par POI")
    ap.add_argument("--pause", type=float, default=0.1, help="pause entre appels (s)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.environ.get("NAVITIA_TOKEN")
    if not token:
        raise SystemExit("Définis la variable d'environnement NAVITIA_TOKEN.")
    nav = Navitia(token, pause=args.pause)

    for step in [s.strip() for s in args.steps.split(",") if s.strip()]:
        if step not in STEPS:
            raise SystemExit(f"Étape inconnue : {step} (choix : {', '.join(STEPS)})")
        log.info("=== étape %s ===", step)
        STEPS[step](nav, args)
    log.info("Terminé : %d appels API réels.", nav.n_calls)


if __name__ == "__main__":
    main()
