"""Position des trains d'un trajet à un instant donné, sans dépendance à Dash.

Un train qui circule entre deux gares est placé sur son tracé selon le temps écoulé depuis son départ, avec un profil réaliste : il accélère, roule à sa vitesse
de croisière, puis freine (voir profil()). À mi-temps, il est à mi-chemin.
Les horaires viennent de l'API SNCF en temps réel (retards compris) : un train retardé arrive plus tard, donc avance moins vite sur le même tracé.

Usage :
    suivi = suivre(etapes, maintenant)       # etapes : voir lib.itineraire.tracer_trajet ; maintenant : datetime (heure de Paris)
    suivi["trains"]    # un dict par train en route : libelle, style, lat, lon, cap (degrés, 0 = nord), avancement (0 à 1), retard_min, vitesse_kmh, reste_km
    suivi["message"]   # « TGV INOUI 6106 : 42 % du parcours », « part à 07:14 », « Trajet terminé »…
    horloge_simulee(depart, t0_reel, maintenant, vitesse)   # heure simulée : le trajet défile à `vitesse` fois la vitesse réelle
"""
import math
from datetime import datetime, timedelta

from lib.reseau_ferre import longueur_km

VITESSE_SIMULATION = 120          # 1 seconde réelle = 2 minutes de trajet
ACCELERATION_PAR_DEFAUT = 0.7     # m/s²


def _lonlat(point):
    return point[1], point[0]


def _cumul(points):
    """Distances cumulées en km le long d'un tracé [[lat, lon], …]."""
    total, cumul = 0.0, [0.0]
    for a, b in zip(points, points[1:]):
        total += longueur_km([_lonlat(a), _lonlat(b)])
        cumul.append(total)
    return cumul


def _cap(a, b):
    """Direction de a vers b en degrés (0 = nord, 90 = est)."""
    dlat, dlon = b[0] - a[0], (b[1] - a[1]) * math.cos(math.radians((a[0] + b[0]) / 2))
    return (math.degrees(math.atan2(dlon, dlat)) + 360) % 360


def point_a(points, fraction):
    """(lat, lon, cap) au bout de `fraction` (0 à 1) de la longueur d'un tracé [[lat, lon], …]."""
    if len(points) < 2:
        return points[0][0], points[0][1], 0.0
    cumul = _cumul(points)
    cible = min(max(fraction, 0.0), 1.0) * cumul[-1]
    i = next((k for k in range(1, len(cumul)) if cumul[k] >= cible), len(cumul) - 1)
    reste = (cible - cumul[i - 1]) / (cumul[i] - cumul[i - 1]) if cumul[i] > cumul[i - 1] else 0.0
    (lat1, lon1), (lat2, lon2) = points[i - 1], points[i]
    return lat1 + (lat2 - lat1) * reste, lon1 + (lon2 - lon1) * reste, _cap(points[i - 1], points[i])


def horloge_simulee(depart, t0_reel, maintenant, vitesse=VITESSE_SIMULATION):
    """Heure simulée : on part de `depart` au moment `t0_reel` (datetimes), puis le temps s'écoule `vitesse` fois plus vite."""
    return depart + timedelta(seconds=(maintenant - t0_reel).total_seconds() * vitesse)


def profil(distance_m, duree_s, acceleration=ACCELERATION_PAR_DEFAUT):
    """Mouvement entre deux gares : le train accélère, roule à sa vitesse de croisière, puis freine, de façon à parcourir `distance_m` en `duree_s`.
    Retourne une fonction t (secondes depuis le départ) → (distance parcourue en m, vitesse en m/s). Même calcul que src/assets/trains.js.
    Si l'horaire est trop serré pour l'accélération donnée, elle est augmentée (profil triangulaire : accélération puis freinage, sans croisière)."""
    duree_s = max(duree_s, 1.0)
    a = acceleration
    if a * a * duree_s ** 2 < 4 * a * distance_m:
        a = 4 * distance_m / duree_s ** 2
    vc = (a * duree_s - math.sqrt(max(a * a * duree_s ** 2 - 4 * a * distance_m, 0.0))) / 2
    ta = vc / a if a > 0 else 0.0

    def etat(t):
        t = min(max(t, 0.0), duree_s)
        if t < ta:
            return 0.5 * a * t * t, a * t
        if t > duree_s - ta:
            u = duree_s - t
            return distance_m - 0.5 * a * u * u, a * u
        return 0.5 * a * ta * ta + vc * (t - ta), vc
    return etat


def _heure(t):
    return t.strftime("%H:%M")


def suivre(etapes, maintenant):
    """Trains en route à l'instant `maintenant` et message d'état. Les étapes à pied n'ont pas de train : elles sont ignorées."""
    trains = [e for e in etapes if not e.get("marche") and e.get("depart") and e.get("arrivee")]
    if not trains:
        return {"trains": [], "message": "Pas d'horaire pour ce trajet."}
    en_route, message = [], ""
    for e in sorted(trains, key=lambda e: e["depart"]):
        depart, arrivee = datetime.fromisoformat(e["depart"]), datetime.fromisoformat(e["arrivee"])
        if depart <= maintenant <= arrivee and arrivee > depart:
            distance_m = _cumul(e["points"])[-1] * 1000
            parcouru, vitesse = profil(distance_m, (arrivee - depart).total_seconds(), e.get("acc") or ACCELERATION_PAR_DEFAUT)((maintenant - depart).total_seconds())
            avancement = parcouru / distance_m if distance_m > 0 else 1.0
            lat, lon, cap = point_a(e["points"], avancement)
            retard = e.get("retard_min") or 0
            en_route.append({"libelle": e["libelle"], "style": e["style"], "lat": lat, "lon": lon, "cap": cap, "avancement": avancement, "retard_min": retard,
                             "vitesse_kmh": vitesse * 3.6, "reste_km": (distance_m - parcouru) / 1000})
            message = (f"{e['libelle']} : {round(avancement * 100)} % du parcours · {round(vitesse * 3.6)} km/h · il reste {(distance_m - parcouru) / 1000:.0f} km"
                       + (f" · retard de {retard} min" if retard else " · à l'heure"))
    if en_route:
        return {"trains": en_route, "message": message}
    premier = min(datetime.fromisoformat(e["depart"]) for e in trains)
    dernier = max(datetime.fromisoformat(e["arrivee"]) for e in trains)
    if maintenant < premier:
        attente = premier - maintenant
        jours, heures = attente.days, attente.seconds // 3600
        dans = f"dans {jours} j {heures} h" if jours else f"dans {heures} h {attente.seconds % 3600 // 60:02d}" if heures else f"dans {attente.seconds // 60} min"
        return {"trains": [], "message": f"Le premier train part le {premier:%d/%m} à {_heure(premier)} ({dans}). Utilisez « Simuler le trajet » pour le voir rouler."}
    if maintenant > dernier:
        return {"trains": [], "message": f"Trajet terminé (arrivée à {_heure(dernier)})."}
    return {"trains": [], "message": "Correspondance : prochain train en gare."}
