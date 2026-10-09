"""Transformation des festivals : nettoie la liste des festivals en France (ministère de la Culture), puis remplit evenement,
evenement_lieu, evenement_periode et lieu avec la source « festivals ».

Usage : python src/transformation/festival.py   (les gares doivent déjà être chargées : voir transformation.py)
Relançable sans risque : les festivals de la source sont remplacés (tout passe ou rien).

Le fichier ne donne pas de dates mais une période de l'année : une saison (« Saison (21 juin - 5 septembre) ») ou des mois.
Règle de gestion : chaque festival reçoit une période par année de ANNEES (l'année en cours et la suivante), couvrant toute sa saison
ou tout son mois. Ce sont des fenêtres approximatives, pas les dates exactes (celles de DATAtourisme, source « datatourisme_fma », le sont).
Écartés : sans nom, sans position, hors de la France continentale (Corse et outre-mer compris), doublons d'identifiant, et ceux dont la
période est absente ou « variable » (pas de fenêtre à leur donner).
Catégorie : toujours « Festival » (la discipline dominante n'est pas conservée). Le chevauchement avec datatourisme_fma est négligeable
(une soixantaine de noms identiques sur 7 283) : les deux sources sont gardées telles quelles.
"""
import calendar
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

import evenement
from geo import dans_la_france_continentale, departement_et_commune, en_france_continentale
from lieux import lire_gares, rattacher_aux_gares

SOURCE = "festivals"
FICHIER = ROOT / "data" / "festivals" / "festivals-global-festivals-pl.csv"
ANNEES = (dt.date.today().year, dt.date.today().year + 1)
# saison → ((mois, jour) de début, (mois, jour) de fin)
SAISONS = {"avant-saison": ((1, 1), (6, 20)), "après-saison": ((9, 6), (12, 31)), "saison": ((6, 21), (9, 5))}
MOIS = {"janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "août": 8,
        "septembre": 9, "octobre": 10, "ocotbre": 10, "novembre": 11, "décembre": 12}   # « Ocotbre » : faute présente dans le fichier


def _lire(fichier=FICHIER):
    df = pd.read_csv(fichier, sep=";", dtype=str, encoding="utf-8-sig", low_memory=False)
    df.columns = [c.lstrip("﻿") for c in df.columns]       # le fichier commence par deux marques d'ordre des octets
    return df


def fenetres(texte):
    """Liste de ((mois, jour) de début, (mois, jour) de fin) d'un texte de période. Vide si la période est absente ou variable."""
    if not isinstance(texte, str):
        return []
    bas = texte.strip().lower()
    for saison, fenetre in SAISONS.items():
        if bas.startswith(saison):
            return [fenetre]
    mots = set(re.findall(r"[a-zéèêûôî]+", bas))
    return [((m, 1), (m, calendar.monthrange(2001, m)[1])) for nom, m in MOIS.items() if nom in mots]


def periodes(texte, annees=ANNEES):
    """DataFrame date_debut, date_fin : une ligne par fenêtre et par année."""
    plages = [(dt.date(a, *debut), dt.date(a, *fin)) for a in annees for debut, fin in fenetres(texte)]
    return pd.DataFrame(plages, columns=["date_debut", "date_fin"])


def nettoyer(df, annees=ANNEES):
    """Retourne (evenements, periodes) au même format que evenement.nettoyer : evenements (nom, categorie, adresse, commune,
    departement, lat, lon), periodes (evenement = indice de la ligne d'evenements, date_debut, date_fin)."""
    departement, _ = departement_et_commune(df["Code postal (de la commune principale de déroulement)"].fillna("") + "#")
    xy = df["Géocodage xy"].str.extract(r"^\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*$").astype(float)
    ev = pd.DataFrame({
        "id": df["Identifiant"],
        "nom": df["Nom du festival"].str.strip(),
        "categorie": "Festival",
        "adresse": df["Adresse postale"].str.strip(),
        "commune": df["Commune principale de déroulement"].str.strip(),
        "departement": departement,
        "lat": xy[0], "lon": xy[1],
        "periode": df["Période principale de déroulement du festival"],
    })
    valides = (ev["nom"].fillna("").ne("") & en_france_continentale(ev["departement"])
               & dans_la_france_continentale(ev["lat"], ev["lon"]))
    ev = ev[valides]
    ev = ev[ev["id"].isna() | ~ev["id"].duplicated()]            # un identifiant vide n'est pas un doublon
    morceaux = {i: periodes(t, annees) for i, t in ev["periode"].items()}
    avec_periode = [i for i, p in morceaux.items() if len(p)]
    ev = ev.loc[avec_periode].drop(columns=["id", "periode"]).reset_index(drop=True)
    pos = {i: n for n, i in enumerate(avec_periode)}
    plages = pd.concat([p.assign(evenement=pos[i]) for i, p in morceaux.items() if i in pos], ignore_index=True)
    return ev, plages[["evenement", "date_debut", "date_fin"]]


def transformer():
    brut = _lire()
    evenements, plages = nettoyer(brut)
    gares = lire_gares()
    if gares.empty:
        sys.exit("Aucune gare en base : lancer d'abord l'étape gares (python src/transformation/transformation.py)")
    nb, nb_periodes = evenement.charger(rattacher_aux_gares(evenements, gares), plages, SOURCE)
    print(f"Festivals : {nb} chargés avec {nb_periodes} périodes ({len(brut) - nb} écartés sur {len(brut)} : doublons, "
          f"hors France continentale, position invalide ou période absente/variable)")
    return nb, nb_periodes


if __name__ == "__main__":
    transformer()
