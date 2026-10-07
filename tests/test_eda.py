"""Tests des fonctions communes de l'analyse exploratoire (lib/eda.py), sur des données synthétiques."""
import pandas as pd

from lib import eda


def test_pair_from_strings_gere_les_deux_ordres():
    s = pd.Series(["48.8, 2.3", "[2.3,48.8]"])
    assert eda.pair_from_strings(s, "latlon")[0].iloc[0] == 48.8
    lat, lon = eda.pair_from_strings(s, "lonlat")
    assert (lat.iloc[1], lon.iloc[1]) == (48.8, 2.3)


def test_active_events_coupe_les_recurrences_apres_l_horizon():
    df = pd.DataFrame({"Periodes_regroupees": [
        "2026-01-01<->2026-06-30",                       # déjà passé
        "2026-10-01<->2026-12-31",                       # en cours
        "2027-03-01<->2027-03-05",                       # après l'horizon
        "2026-11-01<->2100-12-31",                       # fin écrêtée à l'horizon
    ]})
    ev = eda.active_events(df, pd.Timestamp("2026-10-06"), pd.Timestamp("2026-12-31"))
    assert list(ev.index) == [1, 3]
    assert ev.fin.max() == pd.Timestamp("2026-12-31")


def test_in_metro_exclut_corse_et_outre_mer():
    g = pd.DataFrame({"lat": [48.8, 41.9, -21.1], "lon": [2.3, 8.7, 55.5]})
    assert len(eda.in_metro(g)) == 1
    assert len(eda.in_metro(g, corse=True)) == 2


def _gtfs_jouet():
    return {
        "stops": pd.DataFrame({"stop_id": ["StopPoint:OCETrain TER-1", "StopPoint:OCETrain TER-2"],
                               "stop_lat": [48.0, 50.0], "stop_lon": [2.0, 2.0]}),
        "trips": pd.DataFrame({"route_id": ["R"], "service_id": [1], "trip_id": ["T"], "trip_headsign": ["1234"]}),
        "routes": pd.DataFrame({"route_id": ["R"], "route_long_name": ["A - B"], "route_type": [2]}),
        "calendar_dates": pd.DataFrame({"service_id": [1], "date": [20261007], "exception_type": [1]}),
        "stop_times": pd.DataFrame({"trip_id": ["T", "T"], "arrival_time": ["10:00:00", "12:00:00"],
                                    "departure_time": ["10:00:00", "12:00:00"],
                                    "stop_id": ["StopPoint:OCETrain TER-1", "StopPoint:OCETrain TER-2"], "stop_sequence": [0, 1]}),
    }


def test_train_positions_interpole_entre_deux_arrets():
    g = _gtfs_jouet()
    sched = eda.build_schedule(g)
    p = eda.train_positions(g, sched, pd.Timestamp("2026-10-07 11:00"))     # mi-parcours
    assert len(p) == 1 and p.etat.iloc[0] == "en marche"
    assert abs(p.lat.iloc[0] - 49.0) < 1e-6
    assert p.service.iloc[0] == "Train TER" and p.numero.iloc[0] == "1234"


def test_train_positions_aucun_train_hors_service():
    g = _gtfs_jouet()
    sched = eda.build_schedule(g)
    assert eda.train_positions(g, sched, pd.Timestamp("2026-10-07 09:00")).empty     # avant le départ
    assert eda.train_positions(g, sched, pd.Timestamp("2026-10-08 11:00")).empty     # service non actif ce jour-là
