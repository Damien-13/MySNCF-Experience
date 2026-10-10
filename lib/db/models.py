"""Tables de la base (SQLAlchemy). Chaque évolution passe par une nouvelle migration dans migrations/versions/.

Transport (GTFS, tous réseaux) : reseau → ligne → circulation → passage → arret.
Emplacements : lieu (gare, arrêt de bus, station vélo, culture, tourisme…) ; gare et station_velo en précisent le type.
Tracé du réseau ferré national : troncon_voie (polylignes, sans lien avec les tables de transport) ; trace_trajet en déduit le tracé entre deux arrêts consécutifs.
Tracé des cars : ligne_bus (lignes de bus d'OpenStreetMap) et troncon_route (routes entre carrefours), sans lien avec les tables de transport.
Événements : evenement → evenement_lieu → lieu, et evenement_periode.
Identifiants GTFS préfixés par le réseau (« sncf:… ») pour rester uniques entre réseaux.
Heures de passage en secondes depuis minuit (peuvent dépasser 86400 pour les trains de nuit).
"""
import datetime as dt

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String, Text, Time
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ── Transport ───────────────────────────────────────────────────────────────────
class Reseau(Base):
    """Exploitant : SNCF, Eurostar, bus de Marseille…"""
    __tablename__ = "reseau"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    nom: Mapped[str] = mapped_column(String)
    mode: Mapped[str | None] = mapped_column(String)             # train, bus, tram…
    source: Mapped[str | None] = mapped_column(String)           # dossier de data/ d'où vient le réseau


class Ligne(Base):
    """Ligne commerciale, sans horaire (« Marseille – Toulon »)."""
    __tablename__ = "ligne"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    reseau_id: Mapped[str] = mapped_column(ForeignKey("reseau.id"), index=True)
    nom: Mapped[str | None] = mapped_column(String)
    type_transport: Mapped[str | None] = mapped_column(String)   # TGV, TER, Intercités, bus…
    couleur: Mapped[str | None] = mapped_column(String)


class Circulation(Base):
    """Un départ numéroté d'un train ou d'un bus sur une ligne (le 86123 de 7h02)."""
    __tablename__ = "circulation"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    ligne_id: Mapped[str] = mapped_column(ForeignKey("ligne.id"), index=True)
    service_id: Mapped[str] = mapped_column(String, index=True)  # jours de circulation : voir calendrier
    numero: Mapped[str | None] = mapped_column(String, index=True)
    destination: Mapped[str | None] = mapped_column(String)


class Calendrier(Base):
    """Un jour où roule un service. service_id n'est pas unique ici : pas de clé étrangère depuis circulation."""
    __tablename__ = "calendrier"
    service_id: Mapped[str] = mapped_column(String, primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True, index=True)


class Passage(Base):
    """Arrêt desservi par une circulation, avec ses heures."""
    __tablename__ = "passage"
    circulation_id: Mapped[str] = mapped_column(ForeignKey("circulation.id"), primary_key=True)
    ordre: Mapped[int] = mapped_column(Integer, primary_key=True)
    arret_id: Mapped[str] = mapped_column(ForeignKey("arret.id"), index=True)
    heure_arrivee: Mapped[int | None] = mapped_column(Integer)
    heure_depart: Mapped[int | None] = mapped_column(Integer)


# ── Emplacements ────────────────────────────────────────────────────────────────
class Lieu(Base):
    """Tout ce qui a une position sur la carte. gare_proche_id : gare la plus proche, calculée à la transformation."""
    __tablename__ = "lieu"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String, index=True)        # gare, arret_bus, station_velo, culture, tourisme, evenement
    source: Mapped[str | None] = mapped_column(String)           # basilic, datatourisme_place…
    nom: Mapped[str | None] = mapped_column(String)
    adresse: Mapped[str | None] = mapped_column(String)
    commune: Mapped[str | None] = mapped_column(String)
    departement: Mapped[str | None] = mapped_column(String, index=True)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    gare_proche_id: Mapped[int | None] = mapped_column(ForeignKey("lieu.id"), index=True)
    distance_gare_km: Mapped[float | None] = mapped_column(Float)


class Gare(Base):
    __tablename__ = "gare"
    lieu_id: Mapped[int] = mapped_column(ForeignKey("lieu.id"), primary_key=True)
    code_uic: Mapped[str | None] = mapped_column(String, unique=True)


class GareHoraire(Base):
    """Ouverture de la gare un jour de la semaine (0 = lundi)."""
    __tablename__ = "gare_horaire"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gare_id: Mapped[int] = mapped_column(ForeignKey("gare.lieu_id"), index=True)
    jour: Mapped[int] = mapped_column(Integer)
    heure_ouverture: Mapped[dt.time | None] = mapped_column(Time)
    heure_fermeture: Mapped[dt.time | None] = mapped_column(Time)


class Arret(Base):
    """Arrêt tel que décrit dans un GTFS. Plusieurs arrêts d'une même gare pointent vers le même lieu."""
    __tablename__ = "arret"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    reseau_id: Mapped[str] = mapped_column(ForeignKey("reseau.id"), index=True)
    lieu_id: Mapped[int | None] = mapped_column(ForeignKey("lieu.id"), index=True)
    nom: Mapped[str | None] = mapped_column(String)


class StationVelo(Base):
    """Station de vélos en libre-service ou stationnement. La disponibilité en temps réel n'est pas stockée."""
    __tablename__ = "station_velo"
    lieu_id: Mapped[int] = mapped_column(ForeignKey("lieu.id"), primary_key=True)
    reseau: Mapped[str | None] = mapped_column(String)
    capacite: Mapped[int | None] = mapped_column(Integer)


# ── Tracé ferroviaire ───────────────────────────────────────────────────────────
class TronconVoie(Base):
    """Morceau de voie ferrée du réseau ferré national (SNCF Réseau), à ne pas confondre avec `ligne` (ligne commerciale).
    source : « voies » (une voie) ou « lignes » (tracé de la ligne, utilisé là où les voies manquent).
    geometrie : liste JSON de points [[lon, lat], …], simplifiée."""
    __tablename__ = "troncon_voie"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String, index=True)
    code_ligne: Mapped[str] = mapped_column(String, index=True)  # code SNCF Réseau de la ligne (« 125000 »)
    type_voie: Mapped[str | None] = mapped_column(String)        # VPL, VPA (null pour source « lignes »)
    nom_voie: Mapped[str | None] = mapped_column(String)
    geometrie: Mapped[str] = mapped_column(Text)
    longueur_km: Mapped[float | None] = mapped_column(Float)


class TraceTrajet(Base):
    """Tracé d'un train entre deux arrêts qui se suivent dans au moins une circulation, calculé sur troncon_voie.
    sur_voie faux : pas de chemin fiable sur le réseau (gare étrangère, hors réseau ou détour absurde), le tracé est une ligne droite.
    geometrie : liste JSON de points [[lon, lat], …], du premier arrêt au second."""
    __tablename__ = "trace_trajet"
    arret_depart_id: Mapped[str] = mapped_column(ForeignKey("arret.id"), primary_key=True)
    arret_arrivee_id: Mapped[str] = mapped_column(ForeignKey("arret.id"), primary_key=True)
    geometrie: Mapped[str] = mapped_column(Text)
    longueur_km: Mapped[float | None] = mapped_column(Float)
    sur_voie: Mapped[bool] = mapped_column(Boolean)


# ── Événements ──────────────────────────────────────────────────────────────────
class Evenement(Base):
    __tablename__ = "evenement"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str | None] = mapped_column(String)
    nom: Mapped[str | None] = mapped_column(String)
    categorie: Mapped[str | None] = mapped_column(String)


class EvenementLieu(Base):
    """Un événement peut avoir lieu à plusieurs endroits."""
    __tablename__ = "evenement_lieu"
    evenement_id: Mapped[int] = mapped_column(ForeignKey("evenement.id"), primary_key=True)
    lieu_id: Mapped[int] = mapped_column(ForeignKey("lieu.id"), primary_key=True, index=True)


class EvenementPeriode(Base):
    __tablename__ = "evenement_periode"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evenement_id: Mapped[int] = mapped_column(ForeignKey("evenement.id"), index=True)
    date_debut: Mapped[dt.date] = mapped_column(Date, index=True)
    date_fin: Mapped[dt.date] = mapped_column(Date)


# ── Tracé des lignes de bus ─────────────────────────────────────────────────────
class LigneBus(Base):
    """Ligne de bus ou de car telle que dessinée dans OpenStreetMap (relation route=bus), sans lien avec les tables de transport :
    on la retrouve par la position des arrêts (voir lib/trace_bus.py).
    geometrie : liste JSON de polylignes [[[lon, lat], …], …], une par tronçon de route, dans l'ordre de la relation, simplifiées.
    lat_min…lon_max : boîte englobante, pour chercher les lignes qui passent près d'un arrêt."""
    __tablename__ = "ligne_bus"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)   # identifiant de la relation OSM
    ref: Mapped[str | None] = mapped_column(String, index=True)  # numéro de la ligne (« 89047 », « 12 »)
    nom: Mapped[str | None] = mapped_column(String)
    reseau: Mapped[str | None] = mapped_column(String)           # tag network (« ZOU ! »)
    exploitant: Mapped[str | None] = mapped_column(String)       # tag operator
    de: Mapped[str | None] = mapped_column(String)
    vers: Mapped[str | None] = mapped_column(String)
    geometrie: Mapped[str] = mapped_column(Text)
    longueur_km: Mapped[float | None] = mapped_column(Float)
    lat_min: Mapped[float] = mapped_column(Float, index=True)
    lat_max: Mapped[float] = mapped_column(Float, index=True)
    lon_min: Mapped[float] = mapped_column(Float, index=True)
    lon_max: Mapped[float] = mapped_column(Float, index=True)


# ── Réseau routier ──────────────────────────────────────────────────────────────
class TronconRoute(Base):
    """Morceau de route entre deux carrefours (OpenStreetMap), pour tracer un car arrêt par arrêt (lib/reseau_routier.py).
    Seules les routes où un car peut passer sont gardées : ni pistes, ni chemins, ni voies de service.
    classe : type de route OpenStreetMap (motorway, trunk, primary, secondary, tertiary, unclassified, residential, busway…), qui donne la vitesse.
    sens : 0 double sens, 1 sens unique dans le sens de la géométrie.
    tuile : carré de 0,1° (environ 10 km) du milieu du tronçon, pour charger rapidement les routes d'une zone.
    geometrie : liste JSON de points [[lon, lat], …]."""
    __tablename__ = "troncon_route"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    classe: Mapped[str] = mapped_column(String)
    sens: Mapped[int] = mapped_column(Integer)
    tuile: Mapped[int] = mapped_column(Integer, index=True)
    geometrie: Mapped[str] = mapped_column(Text)
    longueur_m: Mapped[float] = mapped_column(Float)
