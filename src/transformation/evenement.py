"""Transformation des événements : nettoie DATAtourisme (fma), puis remplit evenement, evenement_lieu, evenement_periode et lieu.

Usage : python src/transformation/evenement.py   (les gares doivent déjà être chargées : voir transformation.py)
Relançable sans risque : les événements de la source sont remplacés (tout passe ou rien).

Nettoyage :
- Doublons d'identifiant DATAtourisme supprimés ; sans nom ou hors du rectangle de la France continentale écartés ; Corse écartée.
- Catégorie : la plus précise des catégories de l'événement (ordre de CATEGORIES), « autre » à défaut.
- Périodes « début<->fin|début<->fin » : une ligne par période. Écartées : dates illisibles, fin avant début,
  début hors de ANNEE_MIN–ANNEE_MAX (le fichier contient des années 2100 ou 2926) ou plus de DUREE_MAX_JOURS.
  Un événement sans aucune période valide est écarté.
Chaque événement a un lieu (type « evenement ») rattaché à sa gare la plus proche.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import sqlalchemy as sa

from geo import dans_la_france_continentale, departement_et_commune, en_france_continentale
from lib.db.connection import get_engine
from lib.db.models import Evenement, EvenementLieu, EvenementPeriode, Lieu
from lieux import inserer, lignes_lieu, lire_gares, rattacher_aux_gares

SOURCE = "datatourisme_fma"
FICHIER = ROOT / "data" / "datatourisme_fma" / "datatourisme-fma.csv"
ANNEE_MIN, ANNEE_MAX = 2020, 2030
DUREE_MAX_JOURS = 366
# Catégories DATAtourisme, de la plus précise à la plus générale : la première présente est retenue
CATEGORIES = ["Festival", "Concert", "MusicEvent", "TheaterEvent", "ExhibitionEvent", "ScreeningEvent", "ShowEvent", "Market",
              "SportsEvent", "TraditionalCelebration", "ChildrensEvent", "Conference", "BusinessEvent", "SaleEvent",
              "SocialEvent", "CulturalEvent", "LocalAnimation"]


def _lire(fichier=FICHIER):
    return pd.read_csv(fichier, dtype=str, low_memory=False)


def categorie(texte):
    """La catégorie la plus précise parmi celles de l'événement (« autre » si aucune n'est connue)."""
    presentes = {c.rsplit("#", 1)[-1].rsplit("/", 1)[-1] for c in str(texte).split("|")}
    return next((c for c in CATEGORIES if c in presentes), "autre")


def periodes(texte):
    """DataFrame date_debut, date_fin des périodes valides d'un texte « 2026-10-16<->2026-10-18|… »."""
    paires = pd.Series(str(texte).split("|")).str.extract(r"^\s*(\d{4}-\d{2}-\d{2})\s*<->\s*(\d{4}-\d{2}-\d{2})\s*$")
    debut = pd.to_datetime(paires[0], errors="coerce")
    fin = pd.to_datetime(paires[1], errors="coerce")
    ok = (debut.notna() & fin.notna() & (fin >= debut) & debut.dt.year.between(ANNEE_MIN, ANNEE_MAX)
          & ((fin - debut).dt.days <= DUREE_MAX_JOURS))
    return pd.DataFrame({"date_debut": debut[ok].dt.date, "date_fin": fin[ok].dt.date}).drop_duplicates()


def nettoyer(df):
    """Retourne (evenements, periodes). evenements : une ligne par événement (nom, categorie, adresse, commune,
    departement, lat, lon) ; periodes : evenement (indice de la ligne d'evenements), date_debut, date_fin."""
    departement, commune = departement_et_commune(df["Code_postal_et_commune"])
    ev = pd.DataFrame({
        "uri": df["URI_ID_du_POI"],
        "nom": df["Nom_du_POI"].str.strip(),
        "categorie": df["Categories_de_POI"].map(categorie),
        "adresse": df["Adresse_postale"].str.strip(),
        "commune": commune,
        "departement": departement,
        "lat": pd.to_numeric(df["Latitude"], errors="coerce"),
        "lon": pd.to_numeric(df["Longitude"], errors="coerce"),
        "periodes": df["Periodes_regroupees"],
    })
    valides = (ev["nom"].fillna("").ne("") & en_france_continentale(ev["departement"])
               & dans_la_france_continentale(ev["lat"], ev["lon"]))
    ev = ev[valides].drop_duplicates("uri")
    morceaux = {i: periodes(t) for i, t in ev["periodes"].items()}
    avec_periode = [i for i, p in morceaux.items() if len(p)]
    ev = ev.loc[avec_periode].drop(columns=["uri", "periodes"]).reset_index(drop=True)
    pos = {i: n for n, i in enumerate(avec_periode)}
    plages = pd.concat([p.assign(evenement=pos[i]) for i, p in morceaux.items() if i in pos], ignore_index=True)
    return ev, plages[["evenement", "date_debut", "date_fin"]]


def charger(evenements, plages, engine=None):
    """Remplace en une transaction les événements de la source (evenement, evenement_lieu, evenement_periode, lieu).
    `evenements` doit déjà avoir gare_proche_id et distance_gare_km. Retourne (nb événements, nb périodes)."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        anciens = sa.select(Evenement.id).where(Evenement.source == SOURCE)
        anciens_lieux = sa.select(Lieu.id).where(Lieu.type == "evenement", Lieu.source == SOURCE)
        conn.execute(sa.delete(EvenementPeriode).where(EvenementPeriode.evenement_id.in_(anciens)))
        conn.execute(sa.delete(EvenementLieu).where(EvenementLieu.evenement_id.in_(anciens)))
        conn.execute(sa.delete(Evenement).where(Evenement.source == SOURCE))
        conn.execute(sa.delete(EvenementLieu).where(EvenementLieu.lieu_id.in_(anciens_lieux)))
        conn.execute(sa.delete(Lieu).where(Lieu.type == "evenement", Lieu.source == SOURCE))

        premier_lieu = (conn.scalar(sa.select(sa.func.max(Lieu.id))) or 0) + 1
        premier_ev = (conn.scalar(sa.select(sa.func.max(Evenement.id))) or 0) + 1
        n = len(evenements)
        lieux = evenements.drop(columns="categorie").assign(id=range(premier_lieu, premier_lieu + n))
        inserer(conn, Lieu, lignes_lieu(lieux, "evenement", SOURCE))
        ids_ev = pd.Series(range(premier_ev, premier_ev + n))
        inserer(conn, Evenement, [{"id": int(i), "source": SOURCE, "nom": nom, "categorie": cat}
                                  for i, nom, cat in zip(ids_ev, evenements["nom"], evenements["categorie"])])
        inserer(conn, EvenementLieu, [{"evenement_id": int(e), "lieu_id": int(l)} for e, l in zip(ids_ev, lieux["id"])])
        inserer(conn, EvenementPeriode, [{"evenement_id": int(ids_ev[p.evenement]), "date_debut": p.date_debut, "date_fin": p.date_fin}
                                         for p in plages.itertuples()])
    return n, len(plages)


def transformer():
    brut = _lire()
    evenements, plages = nettoyer(brut)
    gares = lire_gares()
    if gares.empty:
        sys.exit("Aucune gare en base : lancer d'abord l'étape gares (python src/transformation/transformation.py)")
    nb, nb_periodes = charger(rattacher_aux_gares(evenements, gares), plages)
    print(f"Événements : {nb} chargés avec {nb_periodes} périodes ({len(brut) - nb} écartés sur {len(brut)} : doublons, "
          f"hors France continentale, position ou périodes invalides)")
    return nb, nb_periodes


if __name__ == "__main__":
    transformer()
