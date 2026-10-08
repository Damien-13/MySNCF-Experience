"""Calculs géographiques communs aux étapes de la transformation."""
import numpy as np

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
