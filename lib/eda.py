"""Fonctions communes de l'analyse exploratoire (notebooks de src/EDA).

Séparées des notebooks pour être réutilisées par la suite (carte des trains, outil décideur).
Aucune URL ni valeur de configuration en dur : les sources viennent du .env via lib.downloader.
"""
import json
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

from lib.downloader import download

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / os.environ.get("DATA_DIR", "data")
SEED = 42
R_TERRE_KM = 6371.0

TABULAR = {".csv", ".txt", ".tsv", ".parquet"}
POIDS_TRANCHES = {"≤ 1 km": 1.0, "1-5 km": 0.5, "5-25 km": 0.1, "> 25 km": 0.0}   # hypothèse de travail
TRANCHES_BINS = [-np.inf, 1, 5, 25, np.inf]


# ── Téléchargement et lecture ───────────────────────────────────────────────────
def has_data(source):
    d = DATA_DIR / source
    return d.is_dir() and any(p.is_file() and p.name != ".gitkeep" for p in d.rglob("*"))


def ensure_sources(sources, force=False):
    """Télécharge les sources absentes du disque. Retourne {source: erreur} pour celles qui échouent."""
    echecs = {}
    for s in sources:
        if force or not has_data(s):
            try:
                download([s])
            except Exception as e:
                echecs[s] = f"{type(e).__name__}: {str(e)[:120]}"
    return echecs


def _clean_cols(df):
    df.columns = [str(c).replace("﻿", "").strip() for c in df.columns]
    return df


def read_table(path, max_rows=500_000):
    """Lit un CSV/TXT/Parquet de façon tolérante. Retourne (df, nb_lignes_approx, echantillonne)."""
    rng = np.random.default_rng(SEED)
    if path.suffix.lower() == ".parquet":
        df = pd.read_parquet(path)
        total = len(df)
        return _clean_cols(df.sample(max_rows, random_state=SEED) if total > max_rows else df), total, total > max_rows

    with open(path, "rb") as f:
        head = f.read(65536).decode("utf-8-sig", errors="replace").replace("﻿", "")
    first = head.splitlines()[0] if head else ""
    sep = max(",;\t|", key=first.count)
    with open(path, "rb") as f:
        total = sum(1 for _ in f) - 1

    sampled = total > 1.5 * max_rows
    frac = max_rows / total if sampled else 1.0
    skip = (lambda i: i > 0 and rng.random() > frac) if sampled else None
    for enc in ("utf-8-sig", "latin-1"):
        for kw in ({"low_memory": False}, {"engine": "python", "on_bad_lines": "skip"}):
            try:
                df = pd.read_csv(path, sep=sep, encoding=enc, skiprows=skip, nrows=None if sampled else max_rows, **kw)
                return _clean_cols(df), total, sampled or total > max_rows
            except UnicodeDecodeError:
                break
            except Exception:
                continue
    raise ValueError(f"illisible : {path.name}")


def load_tables(sources, max_rows=500_000):
    """Charge toutes les tables des sources. Retourne (dict nom→DataFrame, catalogue, illisibles)."""
    tables, rows, bad = {}, [], {}
    for s in sources:
        d = DATA_DIR / s
        for p in sorted(d.rglob("*")) if d.is_dir() else []:
            if p.suffix.lower() not in TABULAR or not p.is_file():
                continue
            key = f"{s}/{p.stem}"
            try:
                df, total, sampled = read_table(p, max_rows)
            except Exception as e:
                bad[key] = str(e)[:100]
                continue
            if df.shape[0] == 0 or df.shape[1] < 2:
                bad[key] = f"vide ou non tabulaire {df.shape}"
                continue
            tables[key] = df
            rows.append(dict(table=key, source=s, lignes=len(df), lignes_fichier=total, echantillon=sampled,
                             colonnes=df.shape[1], taille_Mo=round(p.stat().st_size / 1e6, 1)))
    return tables, pd.DataFrame(rows).set_index("table"), bad


def find(tables, fragment):
    """Première table dont le nom contient `fragment` (None si absente)."""
    return next((df for k, df in tables.items() if fragment in k), None)


def missing_report(tables):
    """Une ligne par colonne : table, colonne, % de valeurs manquantes, nombre de valeurs distinctes."""
    rows = []
    for k, df in tables.items():
        for c in df.columns:
            s = df[c]
            try:
                nu = int(s.nunique(dropna=True))
            except TypeError:
                nu = -1
            rows.append(dict(table=k, colonne=c, manquants_pct=round(100 * s.isna().mean(), 1), uniques=nu))
    return pd.DataFrame(rows)


# ── Temps ──────────────────────────────────────────────────────────────────────
def explode_periods(df, col="Periodes_regroupees"):
    """Périodes d'événements « AAAA-MM-JJ<->AAAA-MM-JJ » (plusieurs par événement) → une ligne par période."""
    pairs = df[col].dropna().str.findall(r"(\d{4}-\d{2}-\d{2})<->(\d{4}-\d{2}-\d{2})").explode().dropna()
    out = pd.DataFrame(pairs.tolist(), index=pairs.index, columns=["deb", "fin"])
    return out.apply(pd.to_datetime, errors="coerce").dropna()


def active_events(df, ref_date, horizon):
    """Événements en cours ou à venir avant l'horizon (les périodes au-delà, souvent des récurrences dépliées, sont coupées)."""
    per = explode_periods(df)
    per = per[(per.deb <= horizon) & (per.fin >= per.deb)].assign(fin=lambda d: d.fin.clip(upper=horizon))
    ev = per.groupby(level=0).agg(deb=("deb", "min"), fin=("fin", "max"))
    return ev[ev.fin >= ref_date]


# ── Géographie ──────────────────────────────────────────────────────────────────
def pair_from_strings(s, order="latlon"):
    """Extrait deux nombres d'une chaîne ('48.8, 2.3' ou '[2.3,48.8]'). order='lonlat' pour les JSON GeoJSON."""
    e = s.astype(str).str.extract(r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)").astype(float)
    return (e[0], e[1]) if order == "latlon" else (e[1], e[0])


def in_metro(g, corse=False):
    """Points en France métropolitaine (Corse exclue par défaut : pas de gares dans gares_voyageurs)."""
    ok = g.lat.between(41, 51.5) & g.lon.between(-5.5, 10)
    if not corse:
        ok &= ~((g.lat < 43.1) & (g.lon > 8.4))
    return g[ok]


GEO_SPEC = [   # (calque, fragment de table, colonne(s), mode)
    ("gares", "gares_voyageurs", "Position géographique", "pair_latlon"),
    ("basilic", "basilic", ("Latitude", "Longitude"), "cols"),
    ("datatourisme", "datatourisme_place", ("Latitude", "Longitude"), "cols"),
    ("événements", "datatourisme_fma", ("Latitude", "Longitude"), "cols"),
    ("vélo_gares_cvl", "velo_stationnement", "coordonneesxy", "pair_lonlat"),
    ("velib", "vls_paris_velib", "Coordonnées géographiques", "pair_latlon"),
]


def build_geo(tables, spec=GEO_SPEC):
    """Calques {nom: DataFrame(lat, lon)} alignés sur l'index de leur table, quel que soit le format source."""
    geo = {}
    for name, frag, col, mode in spec:
        df = find(tables, frag)
        if df is None:
            continue
        if mode == "cols":
            if not set(col) <= set(df.columns):
                continue
            lat, lon = pd.to_numeric(df[col[0]], errors="coerce"), pd.to_numeric(df[col[1]], errors="coerce")
        else:
            if col not in df:
                continue
            lat, lon = pair_from_strings(df[col], "latlon" if mode == "pair_latlon" else "lonlat")
        geo[name] = pd.DataFrame({"lat": lat, "lon": lon}, index=df.index)
    return geo


def nearest_km(points, stations):
    """Distance (km, à vol d'oiseau) de chaque point à la gare la plus proche."""
    from sklearn.neighbors import BallTree
    tree = BallTree(np.radians(stations[["lat", "lon"]].values), metric="haversine")
    d, _ = tree.query(np.radians(points[["lat", "lon"]].values), k=1)
    return d[:, 0] * R_TERRE_KM


def _dep_from_postal(s):
    return s.astype(str).str.extract(r"(\d{5})")[0].str[:2]


def build_sites(tables, ref_date, horizon):
    """Tableau unique des sites (culture, tourisme, événements à venir) avec distance à la gare, tranche, poids et département.

    Retourne (POIS, noms_departements). POIS est vide si les sources nécessaires manquent.
    """
    geo = build_geo(tables)
    if "gares" not in geo:
        return pd.DataFrame(), {}
    stations = in_metro(geo["gares"]).dropna()

    parts, noms = [], {}
    def add(label, layer, dep, keep=None):
        if layer not in geo:
            return
        p = in_metro(geo[layer]).dropna()
        if keep is not None:
            p = p.loc[p.index.intersection(keep)]
        p = p.assign(km=nearest_km(p, stations), source=label, dep=dep.reindex(p.index))
        parts.append(p)

    b = find(tables, "basilic")
    if b is not None and "N_Département" in b:
        dep_b = b["N_Département"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(2)
        add("Culture (Basilic)", "basilic", dep_b)
        if "Département" in b:
            tmp = pd.DataFrame({"c": dep_b, "n": b["Département"]}).dropna().drop_duplicates("c")
            noms = tmp.set_index("c").n.to_dict()
    dtm = find(tables, "datatourisme_place")
    if dtm is not None:
        add("Tourisme (DATATourisme)", "datatourisme", _dep_from_postal(dtm.Code_postal_et_commune))
    fma = find(tables, "datatourisme_fma")
    if fma is not None and "Periodes_regroupees" in fma:
        actifs = active_events(fma, ref_date, horizon)
        add("Événements à venir (fin 2026)", "événements", _dep_from_postal(fma.Code_postal_et_commune), keep=actifs.index)

    if not parts:
        return pd.DataFrame(), noms
    pois = pd.concat(parts, ignore_index=True)
    pois["tranche"] = pd.cut(pois.km, TRANCHES_BINS, labels=list(POIDS_TRANCHES))
    pois["w"] = pois.tranche.map(POIDS_TRANCHES).astype(float)
    return pois, noms


# ── Trains en mouvement (GTFS) ──────────────────────────────────────────────────
def _secs(s):
    """'HH:MM:SS' → secondes ; HH peut dépasser 24 (service de nuit rattaché au jour précédent)."""
    p = s.astype("string").str.split(":", expand=True).astype(float)
    return p[0] * 3600 + p[1] * 60 + p[2]


def load_gtfs(folder):
    """Charge les tables GTFS utiles à la simulation depuis un dossier de data/."""
    d = DATA_DIR / folder
    g = {n: pd.read_csv(d / f"{n}.txt", low_memory=False) for n in ["stops", "trips", "routes", "calendar_dates"]}
    g["stop_times"] = pd.read_csv(d / "stop_times.txt", usecols=["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"])
    return g


def build_schedule(gtfs):
    """Une ligne par tronçon (arrêt → arrêt suivant) avec heures en secondes et coordonnées des deux extrémités."""
    st = gtfs["stop_times"].sort_values(["trip_id", "stop_sequence"]).copy()
    st["arr"], st["dep"] = _secs(st.arrival_time), _secs(st.departure_time)
    st["arr"], st["dep"] = st.arr.fillna(st.dep), st.dep.fillna(st.arr)
    sp = gtfs["stops"].set_index("stop_id")
    st["lat"], st["lon"] = st.stop_id.map(sp.stop_lat), st.stop_id.map(sp.stop_lon)
    g = st.groupby("trip_id")
    st["next_arr"], st["next_lat"], st["next_lon"] = g.arr.shift(-1), g.lat.shift(-1), g.lon.shift(-1)
    st["service"] = st.stop_id.str.extract(r"StopPoint:OCE(.+?)-\d")[0].fillna("Autre")
    return st.drop(columns=["arrival_time", "departure_time"])


def active_trips(gtfs, when):
    """Voyages circulant à l'instant `when` d'après le calendrier (calendar_dates, exception_type=1)."""
    cd, trips = gtfs["calendar_dates"], gtfs["trips"]
    t = when.hour * 3600 + when.minute * 60 + when.second
    ids = []
    for back_days, tt in ((0, t), (1, t + 86400)):                    # services du jour, et ceux de la veille après minuit
        day = int((when.normalize() - pd.Timedelta(days=back_days)).strftime("%Y%m%d"))
        sv = cd.loc[(cd.date == day) & (cd.exception_type == 1), "service_id"]
        ids.append((set(trips.loc[trips.service_id.isin(sv), "trip_id"]), tt))
    return ids


def train_positions(gtfs, sched, when):
    """Position interpolée (ligne droite entre deux arrêts) de chaque train en circulation à `when`."""
    out = []
    for trip_ids, tt in active_trips(gtfs, when):
        s = sched[sched.trip_id.isin(trip_ids)]
        mv = s[(s.dep <= tt) & (s.next_arr > tt)].copy()
        f = (tt - mv.dep) / (mv.next_arr - mv.dep)
        mv["lat"], mv["lon"] = mv.lat + f * (mv.next_lat - mv.lat), mv.lon + f * (mv.next_lon - mv.lon)
        mv["etat"] = "en marche"
        dw = s[(s.arr <= tt) & (s.dep > tt)].copy()
        dw["etat"] = "à quai"
        out += [mv, dw]
    pos = pd.concat(out, ignore_index=True).dropna(subset=["lat", "lon"])
    tr = gtfs["trips"].set_index("trip_id")
    pos["route_id"] = pos.trip_id.map(tr.route_id)
    pos["numero"] = pos.trip_id.map(tr.trip_headsign)               # trip_headsign contient le numéro de train
    rt = gtfs["routes"].set_index("route_id")
    pos["ligne"] = pos.route_id.map(rt.route_long_name)
    pos["type"] = pos.route_id.map(rt.route_type)
    return pos[["trip_id", "numero", "lat", "lon", "etat", "service", "ligne", "type"]]


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * R_TERRE_KM * np.arcsin(np.sqrt(a))


def rail_network(tables):
    """Tronçons de voies ferrées (GeoJSON de lignes_par_region) → liste de tableaux [[lon, lat], ...]."""
    df = find(tables, "lignes_par_region")
    if df is None or "Geo Shape" not in df:
        return []
    lines = []
    for raw in df["Geo Shape"].dropna():
        try:
            geom = json.loads(raw)
        except (TypeError, ValueError):
            continue
        coords = geom.get("coordinates", [])
        if geom.get("type") == "MultiLineString":
            lines += [np.array(c) for c in coords]
        elif coords:
            lines.append(np.array(coords))
    return lines
