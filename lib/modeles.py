"""Tables de la base (SQLAlchemy). Chaque évolution passe par une nouvelle migration dans bdd/versions/.

Transport (GTFS, tous réseaux) : reseau → ligne → circulation → passage → arret.
Emplacements : lieu (gare, arrêt de bus, station vélo, culture, tourisme…) ; gare et station_velo en précisent le type.
Événements : evenement → evenement_lieu → lieu, et evenement_periode.
Identifiants GTFS préfixés par le réseau (« sncf:… ») pour rester uniques entre réseaux.
Heures de passage en secondes depuis minuit (peuvent dépasser 86400 pour les trains de nuit).
"""
from datetime import date, time

from sqlalchemy import Date, Float, ForeignKey, Integer, String, Time
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
    date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)


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
    heure_ouverture: Mapped[time | None] = mapped_column(Time)
    heure_fermeture: Mapped[time | None] = mapped_column(Time)


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
    date_debut: Mapped[date] = mapped_column(Date, index=True)
    date_fin: Mapped[date] = mapped_column(Date)
