"""Calculs géographiques communs aux étapes de la transformation."""
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

RAYON_TERRE_KM = 6371.0088
PAQUET = 2_000        # lieux comparés à toutes les gares à la fois (borne la mémoire : PAQUET × nb de gares)


def plus_proche(lat, lon, cibles_lat, cibles_lon):
    """Pour chaque point (lat, lon), l'indice de la cible la plus proche et la distance à vol d'oiseau en km (haversine).
    Retourne (indices, distances) : deux tableaux numpy de la taille de lat. Si cibles est vide, indices = -1 et distances = NaN."""
    lat, lon = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float))
    clat, clon = np.radians(np.asarray(cibles_lat, float)), np.radians(np.asarray(cibles_lon, float))
    indices = np.full(len(lat), -1, dtype=int)
    distances = np.full(len(lat), np.nan)
    if len(clat) == 0:
        return indices, distances
    for debut in range(0, len(lat), PAQUET):
        fin = debut + PAQUET
        dlat = clat[None, :] - lat[debut:fin, None]
        dlon = clon[None, :] - lon[debut:fin, None]
        a = np.sin(dlat / 2) ** 2 + np.cos(lat[debut:fin, None]) * np.cos(clat)[None, :] * np.sin(dlon / 2) ** 2
        proche = a.argmin(axis=1)                  # le plus petit « a » est aussi la plus petite distance
        indices[debut:fin] = proche
        distances[debut:fin] = 2 * RAYON_TERRE_KM * np.arcsin(np.sqrt(a[np.arange(len(proche)), proche]))
    return indices, distances


def en_france_continentale(departements):
    """Série de booléens : département renseigné et ni outre-mer (97x, 98x) ni Corse (2A, 2B, 20).
    La Corse est écartée pour l'instant : aucune gare du fichier ne s'y trouve."""
    dep = pd.Series(departements).fillna("").astype(str).str.strip().str.upper()
    return dep.ne("") & ~dep.str.match(r"^(9[78]|2A|2B|20)")


def departement_et_commune(code_postal_commune):
    """DATAtourisme donne « 37250#Veigné » (parfois plusieurs, séparés par « | »). Retourne (departement, commune) du premier :
    deux premiers chiffres du code postal, trois pour l'outre-mer (97x, 98x). Valeurs vides si le code n'est pas à 5 chiffres."""
    premier = pd.Series(code_postal_commune).fillna("").astype(str).str.split("|").str[0]
    parties = premier.str.split("#", n=1, expand=True).reindex(columns=[0, 1])
    code = parties[0].str.strip()
    code = code.where(code.str.fullmatch(r"\d{5}"), "")
    departement = code.str[:2]
    departement = departement.where(~departement.isin(["97", "98"]), code.str[:3])
    return departement, parties[1].str.strip()


def dans_la_france_continentale(lat, lon):
    """Série de booléens : position dans le rectangle de la France continentale, hors Corse
    (écarte l'étranger, la Corse et les positions aberrantes, y compris quand le département est inconnu)."""
    lat, lon = pd.Series(lat), pd.Series(lon)
    corse = lat.lt(43.3) & lon.gt(8.3)
    return lat.between(41.3, 51.2) & lon.between(-5.3, 9.7) & ~corse


def a_proximite(lat, lon, cibles_lat, cibles_lon, rayon_m):
    """Tableau de booléens : chaque point (lat, lon) a-t-il une cible à moins de `rayon_m` mètres ?
    Distances calculées à plat autour de la position (juste à quelques mètres près en France pour des rayons de quelques dizaines de mètres)."""
    def plat(la, lo):
        la, lo = np.asarray(la, float), np.asarray(lo, float)
        return np.c_[lo * np.cos(np.radians(la)) * 111_320, la * 111_320]
    if len(cibles_lat) == 0:
        return np.zeros(len(lat), dtype=bool)
    distances, _ = cKDTree(plat(cibles_lat, cibles_lon)).query(plat(lat, lon))
    return distances < rayon_m
