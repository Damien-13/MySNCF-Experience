"""Chiffres de l'onglet Analyse de la couverture ferroviaire : indicateurs, graphes et plan d'action, tous calculés avec les mêmes filtres.

Sites analysés : culture, tourisme et événements (les gares, arrêts et stations vélo sont des moyens d'y aller, pas des sites).
Un événement ne compte que s'il a une période qui croise la période choisie ; les sites de culture et de tourisme sont permanents.

Indice d'Accessibilité Ferroviaire (IAF, 0-100) : même définition que l'EDA (src/EDA/eda_recap.ipynb), moyenne pondérée des sites
selon leur distance à vol d'oiseau à la gare la plus proche (POIDS_TRANCHES). Un site sans gare connue vaut 0.

Accès depuis la gare la plus proche (ACCES, graphe 2 et KPI) : à pied jusqu'à SEUIL_PIED_KM ; au-delà, en transport en commun si on peut rejoindre le site
depuis la gare avec au plus une correspondance (lieu.acces_tc, calculé par src/transformation/acces_tc.py) ; sinon voiture seule (zone blanche), comme les sites sans gare.

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
SEUIL_PIED_KM = 1.5                  # à pied depuis la gare
MIN_SITES_DEPARTEMENT = 5            # un département avec moins de sites n'apparaît pas sur le graphe 1 (IAF trop instable)

TYPES_PAR_CATEGORIE = {"tous": ["culture", "tourisme", "evenement"], "culture": ["culture"], "tourisme": ["tourisme"], "evenement": ["evenement"]}
ACCES = ["À pied (≤ 1,5 km)", "Transport en commun", "Voiture seule"]
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


def _acces_sql():
    """Mode d'accès d'un site depuis sa gare la plus proche (une valeur de ACCES)."""
    return (f"CASE WHEN l.distance_gare_km <= {SEUIL_PIED_KM} THEN '{ACCES[0]}' "
            f"WHEN l.acces_tc THEN '{ACCES[1]}' ELSE '{ACCES[2]}' END")


def indicateurs(engine, f):
    """Les trois KPI : part des sites à 1,5 km ou moins d'une gare, leur nombre, part des zones blanches (voiture seule). None si aucun site."""
    where, params = _where(f)
    r = pd.read_sql(sa.text(f"""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN {_acces_sql()} = '{ACCES[0]}' THEN 1 ELSE 0 END) AS a_pied,
               SUM(CASE WHEN {_acces_sql()} = '{ACCES[2]}' THEN 1 ELSE 0 END) AS blancs
        FROM lieu l WHERE {where}"""), engine, params=params).iloc[0]
    total = int(r["total"] or 0)
    if not total:
        return None
    a_pied, blancs = int(r["a_pied"] or 0), int(r["blancs"] or 0)
    return {"total": total, "a_pied": a_pied, "part_a_pied": round(100 * a_pied / total, 1), "part_zones_blanches": round(100 * blancs / total, 1)}


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


def modes_acces(engine, f):
    """Graphe 2 : nombre de sites par mode d'accès depuis la gare la plus proche (ACCES) et par type. Les sites sans gare connue sont en voiture seule."""
    where, params = _where(f)
    return pd.read_sql(sa.text(f"""
        SELECT {_acces_sql()} AS acces, l.type AS type, COUNT(*) AS sites
        FROM lieu l WHERE {where} GROUP BY 1, 2"""), engine, params=params)


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
    """Plan d'action : les sites les plus loin d'une gare (mode « pires ») ou les plus proches, avec la gare et le dernier kilomètre."""
    where, params = _where(f)
    ordre = "DESC" if mode == "pires" else "ASC"
    return pd.read_sql(sa.text(f"""
        SELECT l.nom AS "SITE TOURISTIQUE",
               COALESCE(g.nom, 'Gare inconnue') || ' (' || ROUND(l.distance_gare_km, 1) || ' km)' AS "GARE LA + PROCHE",
               {_acces_sql()} AS "DERNIER KM",
               CASE WHEN l.distance_gare_km > 15 THEN 'Urgente'
                    WHEN l.distance_gare_km > 5 THEN 'Élevée'
                    WHEN l.distance_gare_km > 1.5 THEN 'Moyenne'
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
            "acces": modes_acces(engine, f), "saison": saisonnalite(engine, f)}
