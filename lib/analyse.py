"""Chiffres de l'onglet Analyse de la couverture ferroviaire : indicateurs, graphes et plan d'action, tous calculés avec les mêmes filtres.

Sites analysés : culture, tourisme et événements (les gares, arrêts et stations vélo sont des moyens d'y aller, pas des sites).
Un événement ne compte que s'il a une période qui croise la période choisie ; les sites de culture et de tourisme sont permanents.

Accès d'un site depuis le train (ACCES), selon sa distance à vol d'oiseau à la gare la plus proche : à pied jusqu'à SEUIL_PIED_KM,
en transport en commun jusqu'à SEUIL_TC_KM, au-delà (ou sans gare connue) voiture obligatoire : il faudrait plusieurs transports en commun.

Indice d'Accessibilité Ferroviaire (IAF, 0-100) : même définition que l'EDA (src/EDA/eda_recap.ipynb), moyenne pondérée des sites
selon leur distance à vol d'oiseau à la gare la plus proche (POIDS_TRANCHES). Un site sans gare connue vaut 0.

Les requêtes sont paramétrées (aucune valeur saisie n'est collée dans le SQL). Une base absente lève une exception : à l'appelant
de l'afficher, jamais de données inventées à la place.

    from lib.analyse import Filtres, donnees
    d = donnees(engine, Filtres(categorie="culture", departements=["13"], debut="2026-10-23", fin="2027-10-23"))
"""
from dataclasses import dataclass, field

import pandas as pd
import sqlalchemy as sa

# Poids de l'IAF par tranche de distance (km, poids), comme POIDS_TRANCHES dans l'EDA ; au-delà de la dernière tranche, 0.
POIDS_TRANCHES = [(1, 1.0), (5, 0.5), (25, 0.1)]
SEUIL_PIED_KM = 1.5                  # une gare à 20 minutes de marche
SEUIL_TC_KM = 30                     # au-delà, plusieurs bus ou cars : la voiture devient obligatoire
SEUIL_ELEVE_KM = 15                  # plan d'action : priorité élevée au-delà, en transport en commun
MIN_SITES_DEPARTEMENT = 5            # un département avec moins de sites n'apparaît pas sur le graphe 1 (IAF trop instable)

TYPES_PAR_CATEGORIE = {"tous": ["culture", "tourisme", "evenement"], "culture": ["culture"], "tourisme": ["tourisme"], "evenement": ["evenement"]}
ACCES = {"pied": "À pied (≤ 1,5 km)", "tc": "Transport en commun (1,5 à 30 km)", "voiture": "Voiture obligatoire (> 30 km)"}
ACCES_SQL = f"CASE WHEN l.distance_gare_km <= {SEUIL_PIED_KM} THEN 'pied' WHEN l.distance_gare_km <= {SEUIL_TC_KM} THEN 'tc' ELSE 'voiture' END"
MOIS = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sept", "Oct", "Nov", "Déc"]


@dataclass
class Filtres:
    categorie: str = "tous"
    departements: list = field(default_factory=list)
    destination: str | None = None    # nom exact d'un site
    debut: str | None = None          # période (AAAA-MM-JJ) : seuls les événements qui la croisent comptent
    fin: str | None = None


def _iaf_sql(col="l.distance_gare_km"):
    cas = " ".join(f"WHEN {col} <= {km} THEN {poids}" for km, poids in POIDS_TRANCHES)
    return f"ROUND(100.0 * AVG(CASE {cas} ELSE 0 END), 1)"


def _where(f, departements=True, destination=True):
    """Clause WHERE sur lieu l et ses paramètres. departements/destination=False : la référence France ignore ces filtres."""
    types = TYPES_PAR_CATEGORIE.get(f.categorie, TYPES_PAR_CATEGORIE["tous"])
    params = {f"t{i}": t for i, t in enumerate(types)}
    conditions = [f"l.type IN ({', '.join(':' + k for k in params)})"]
    if departements and f.departements:
        deps = {f"d{i}": str(d) for i, d in enumerate(f.departements)}
        conditions.append(f"l.departement IN ({', '.join(':' + k for k in deps)})")
        params |= deps
    if destination and f.destination:
        conditions.append("l.nom = :destination")
        params["destination"] = f.destination
    if f.debut and f.fin:
        conditions.append("(l.type <> 'evenement' OR EXISTS (SELECT 1 FROM evenement_lieu el JOIN evenement_periode ep ON ep.evenement_id = el.evenement_id "
                          "WHERE el.lieu_id = l.id AND ep.date_debut <= :fin AND ep.date_fin >= :debut))")
        params |= {"debut": str(f.debut)[:10], "fin": str(f.fin)[:10]}
    return " AND ".join(conditions), params


def indicateurs(engine, f):
    """Les trois KPI : nombre et part des sites accessibles à pied, en transport en commun, en voiture obligatoire (zones blanches). None si aucun site."""
    where, params = _where(f)
    df = pd.read_sql(sa.text(f"SELECT {ACCES_SQL} AS acces, COUNT(*) AS n FROM lieu l WHERE {where} GROUP BY 1"), engine, params=params)
    n = {acces: int(v) for acces, v in zip(df["acces"], df["n"])}
    total = sum(n.values())
    if not total:
        return None
    return {"total": total, **{acces: n.get(acces, 0) for acces in ACCES}, **{f"part_{acces}": round(100 * n.get(acces, 0) / total, 1) for acces in ACCES}}


def iaf_departements(engine, f):
    """Graphe 1 : nombre de sites et IAF par département, plus l'IAF France (mêmes filtres sauf département et destination)."""
    where, params = _where(f)
    seuil = 1 if f.destination else MIN_SITES_DEPARTEMENT       # un site choisi par son nom tient souvent dans un seul département
    deps = pd.read_sql(sa.text(f"""
        SELECT l.departement AS departement, COUNT(*) AS sites, {_iaf_sql()} AS iaf
        FROM lieu l WHERE {where} AND l.departement IS NOT NULL
        GROUP BY l.departement HAVING COUNT(*) >= :seuil"""), engine, params=params | {"seuil": seuil})
    where_fr, params_fr = _where(f, departements=False, destination=False)
    france = pd.read_sql(sa.text(f"SELECT {_iaf_sql()} AS iaf FROM lieu l WHERE {where_fr}"), engine, params=params_fr).iloc[0]["iaf"]
    return deps, (None if pd.isna(france) else float(france))


def acces_sites(engine, f):
    """Graphe 3 : nombre de sites par accès depuis la gare (ACCES) et par type."""
    where, params = _where(f)
    return pd.read_sql(sa.text(f"SELECT {ACCES_SQL} AS acces, l.type AS type, COUNT(*) AS sites FROM lieu l WHERE {where} GROUP BY 1, 2"),
                       engine, params=params)


def saisonnalite(engine, f):
    """Graphe 4 : nombre d'événements qui commencent chaque mois de la période, dans les départements et la destination choisis.
    Un mois par ligne, dans l'ordre du calendrier (étiquette « Oct 2026 »). Vide si la catégorie exclut les événements."""
    if "evenement" not in TYPES_PAR_CATEGORIE.get(f.categorie, TYPES_PAR_CATEGORIE["tous"]):
        return pd.DataFrame(columns=["mois", "evenements"])
    where, params = _where(Filtres("evenement", f.departements, f.destination))
    periode = ""
    if f.debut and f.fin:
        periode = "AND ep.date_debut BETWEEN :debut AND :fin"
        params |= {"debut": str(f.debut)[:10], "fin": str(f.fin)[:10]}
    df = pd.read_sql(sa.text(f"""
        SELECT STRFTIME('%Y-%m', ep.date_debut) AS annee_mois, COUNT(DISTINCT ep.evenement_id) AS evenements
        FROM evenement_periode ep
        WHERE ep.evenement_id IN (SELECT el.evenement_id FROM evenement_lieu el JOIN lieu l ON l.id = el.lieu_id WHERE {where}) {periode}
        GROUP BY 1 ORDER BY 1"""), engine, params=params)
    df["mois"] = [f"{MOIS[int(am[5:7]) - 1]} {am[:4]}" for am in df["annee_mois"]]
    return df[["mois", "evenements"]]


def plan_action(engine, f, mode="pires", limite=10):
    """Plan d'action : les sites les plus loin d'une gare (mode « pires ») ou les plus proches, avec la gare, le moyen d'y aller et la priorité."""
    where, params = _where(f)
    ordre = "DESC" if mode == "pires" else "ASC"
    return pd.read_sql(sa.text(f"""
        SELECT l.nom AS "SITE TOURISTIQUE",
               COALESCE(g.nom, 'Gare inconnue') || ' (' || ROUND(l.distance_gare_km, 1) || ' km)' AS "GARE LA + PROCHE",
               CASE {ACCES_SQL} WHEN 'pied' THEN 'À pied' WHEN 'tc' THEN 'Transport en commun' ELSE 'Voiture obligatoire' END AS "DERNIER KM",
               CASE WHEN {ACCES_SQL} = 'voiture' THEN 'Urgente'
                    WHEN l.distance_gare_km > {SEUIL_ELEVE_KM} THEN 'Élevée'
                    WHEN {ACCES_SQL} = 'tc' THEN 'Moyenne'
                    ELSE 'Excellente' END AS "PRIORITÉ"
        FROM lieu l LEFT JOIN lieu g ON l.gare_proche_id = g.id
        WHERE {where} AND l.distance_gare_km IS NOT NULL
        ORDER BY l.distance_gare_km {ordre} LIMIT :limite"""), engine, params=params | {"limite": limite})


def chercher_sites(engine, recherche, limite=50):
    """Options du filtre Destination : noms de sites (culture, tourisme, événement) qui contiennent la recherche."""
    if not recherche or len(recherche.strip()) < 2:
        return []
    noms = pd.read_sql(sa.text("SELECT DISTINCT nom FROM lieu WHERE type IN ('culture', 'tourisme', 'evenement') AND nom LIKE :motif "
                               "ORDER BY nom LIMIT :limite"), engine, params={"motif": f"%{recherche.strip()}%", "limite": limite})
    return noms["nom"].tolist()


def donnees(engine, f):
    """Tout l'onglet en une fois : {"kpi", "departements", "iaf_france", "acces", "saison"}. kpi vaut None si aucun site ne correspond."""
    deps, france = iaf_departements(engine, f)
    return {"kpi": indicateurs(engine, f), "departements": deps, "iaf_france": france,
            "acces": acces_sites(engine, f), "saison": saisonnalite(engine, f)}
