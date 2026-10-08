"""Transformation des gares : nettoie gares_voyageurs et horaires_gares, puis remplit lieu, gare et gare_horaire.

Usage : python src/transformation/gare.py
Relançable sans risque : les gares de la source sont mises à jour (tout passe ou rien), en gardant l'identifiant des gares déjà connues.

Nettoyage :
- Position « lat, lon » (texte) → deux nombres.
- Code UIC : 8 chiffres ; une gare qui en a plusieurs (« 87271494;87001479 ») garde le premier,
  mais ses horaires sont cherchés avec tous.
- Département : deux premiers caractères du code commune INSEE (« 2A » pour la Corse-du-Sud).
- Horaires : UIC à 10 chiffres → 8 ; seul le jour normal est gardé (gare_horaire n'a pas de colonne jour férié).
  Une gare fermée à midi a deux plages le même jour : chacune est une ligne.
"""
import sys
from datetime import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pandas as pd
import sqlalchemy as sa

from lib.db.connection import get_engine
from lib.db.models import Gare, GareHoraire, Lieu

SOURCE = "gares_voyageurs"
FICHIER_GARES = ROOT / "data" / "gares_voyageurs" / "gares-de-voyageurs.csv"
FICHIER_HORAIRES = ROOT / "data" / "horaires_gares" / "horaires-des-gares1.csv"
JOURS = {"Lundi": 0, "Mardi": 1, "Mercredi": 2, "Jeudi": 3, "Vendredi": 4, "Samedi": 5, "Dimanche": 6}


def _lire(fichier):
    """CSV séparé par des points-virgules, tout en texte (les codes gardent leurs zéros), BOM retiré."""
    df = pd.read_csv(fichier, sep=";", encoding="utf-8-sig", dtype=str)
    df.columns = [c.lstrip("﻿").strip() for c in df.columns]
    return df


def nettoyer_gares(df):
    """Une ligne par gare : nom, uic (liste de codes), code_uic (le premier), lat, lon, departement.
    Les gares sans nom, sans code UIC ou sans position valide sont écartées."""
    pos = df["Position géographique"].str.split(",", expand=True)
    out = pd.DataFrame({
        "nom": df["Nom_Gare"].str.strip(),
        "uic": df["Code_UIC"].str.split(";").apply(lambda codes: [c.strip() for c in codes if c.strip()]),
        "lat": pd.to_numeric(pos[0], errors="coerce"),
        "lon": pd.to_numeric(pos[1], errors="coerce"),
        "departement": df["Code commune"].str.strip().str[:2],
    })
    out["code_uic"] = out["uic"].str[0]
    valides = out["nom"].notna() & out["code_uic"].notna() & out["lat"].between(-90, 90) & out["lon"].between(-180, 180)
    return out[valides].drop_duplicates("code_uic").reset_index(drop=True)


def _heure(texte):
    h, m = texte.split(":")
    return time(int(h), int(m))


def nettoyer_horaires(df):
    """Une ligne par plage d'ouverture : uic (8 chiffres), jour (0 = lundi), heure_ouverture, heure_fermeture.
    Les lignes au jour inconnu ou à l'horaire illisible (« Fermée », 24:00…) sont écartées."""
    plages = df["Horaire en jour normal"].str.extract(r"^\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*$")
    out = pd.DataFrame({
        "uic": df["UIC"].str.strip().str[-8:],
        "jour": df["Jour de la semaine"].str.strip().str.capitalize().map(JOURS),
        "ouverture": plages[0],
        "fermeture": plages[1],
    }).dropna()
    out = out[out["ouverture"].str[:2].astype(int).lt(24) & out["fermeture"].str[:2].astype(int).lt(24)]
    out["heure_ouverture"] = out["ouverture"].map(_heure)
    out["heure_fermeture"] = out["fermeture"].map(_heure)
    out["jour"] = out["jour"].astype(int)
    return out.drop(columns=["ouverture", "fermeture"]).drop_duplicates().reset_index(drop=True)


def associer_horaires(gares, horaires):
    """Rattache chaque plage à sa gare via n'importe lequel des codes UIC de la gare.
    Retourne (horaires avec code_uic, nombre de plages sans gare)."""
    vers_gare = {uic: code for code, uics in zip(gares["code_uic"], gares["uic"]) for uic in uics}
    rattaches = horaires.assign(code_uic=horaires["uic"].map(vers_gare))
    return rattaches.dropna(subset=["code_uic"]).drop(columns="uic"), int(rattaches["code_uic"].isna().sum())


def charger(gares, horaires, engine=None):
    """Met à jour en une transaction les gares de la source (lieu, gare, gare_horaire). Retourne (nb gares, nb plages).
    Une gare déjà en base (même code UIC) garde son identifiant : tout ce qui s'y rattache (gare_proche_id des lieux, arrêts) reste valable.
    Les gares qui ne sont plus dans la source sont supprimées ; les horaires sont remplacés en entier."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        des_gares = sa.select(Lieu.id).where(Lieu.type == "gare", Lieu.source == SOURCE)
        anciennes = dict(conn.execute(sa.select(Gare.code_uic, Gare.lieu_id).where(Gare.lieu_id.in_(des_gares))).all())
        conn.execute(sa.delete(GareHoraire).where(GareHoraire.gare_id.in_(des_gares)))

        prochain = (conn.scalar(sa.select(sa.func.max(Lieu.id))) or 0) + 1
        ids, nouvelles = {}, []
        for g in gares.itertuples():
            if g.code_uic in anciennes:
                ids[g.code_uic] = anciennes[g.code_uic]
                conn.execute(sa.update(Lieu).where(Lieu.id == ids[g.code_uic]).values(nom=g.nom, lat=g.lat, lon=g.lon, departement=g.departement))
            else:
                ids[g.code_uic] = prochain + len(nouvelles)
                nouvelles.append(g)
        disparues = [lieu_id for code, lieu_id in anciennes.items() if code not in ids]
        if disparues:
            conn.execute(sa.delete(Gare).where(Gare.lieu_id.in_(disparues)))
            conn.execute(sa.delete(Lieu).where(Lieu.id.in_(disparues)))
        if nouvelles:
            conn.execute(sa.insert(Lieu), [
                {"id": ids[g.code_uic], "type": "gare", "source": SOURCE, "nom": g.nom, "lat": g.lat, "lon": g.lon, "departement": g.departement}
                for g in nouvelles])
            conn.execute(sa.insert(Gare), [{"lieu_id": ids[g.code_uic], "code_uic": g.code_uic} for g in nouvelles])
        plages = [
            {"gare_id": ids[h.code_uic], "jour": h.jour,
             "heure_ouverture": h.heure_ouverture, "heure_fermeture": h.heure_fermeture}
            for h in horaires.itertuples()
        ]
        if plages:
            conn.execute(sa.insert(GareHoraire), plages)
    return len(gares), len(plages)


def transformer():
    """Lit les deux CSV, nettoie, rattache, charge, et affiche ce qui a été écarté."""
    brut_gares, brut_horaires = _lire(FICHIER_GARES), _lire(FICHIER_HORAIRES)
    gares = nettoyer_gares(brut_gares)
    horaires = nettoyer_horaires(brut_horaires)
    horaires, orphelines = associer_horaires(gares, horaires)
    nb_gares, nb_plages = charger(gares, horaires)
    print(f"Gares : {nb_gares} chargées ({len(brut_gares) - nb_gares} écartées sur {len(brut_gares)})")
    print(f"Horaires : {nb_plages} plages chargées ({orphelines} sans gare correspondante, "
          f"{len(brut_horaires) - len(horaires) - orphelines} lignes écartées : doublons du jour férié ou illisibles)")
    return nb_gares, nb_plages


if __name__ == "__main__":
    transformer()
