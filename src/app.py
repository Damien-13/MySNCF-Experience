import sys
import os
from pathlib import Path

# Fix sécurité Windows (AppLocker) : désactive les extensions C de SQLAlchemy
os.environ["DISABLE_SQLALCHEMY_CEXT"] = "1"

# Ajout de la racine du projet au chemin de recherche Python
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import base64
from datetime import date

# ==============================================================================
# 1. DICTIONNAIRE DES DÉPARTEMENTS
# ==============================================================================
DEPARTEMENTS_MAP = {
    "01": "01 - Ain", "02": "02 - Aisne", "03": "03 - Allier", "04": "04 - Alpes-de-Haute-Provence",
    "05": "05 - Hautes-Alpes", "06": "06 - Alpes-Maritimes", "07": "07 - Ardèche", "08": "08 - Ardennes",
    "09": "09 - Ariège", "10": "10 - Aube", "11": "11 - Aude", "12": "12 - Aveyron", "13": "13 - Bouches-du-Rhône",
    "14": "14 - Calvados", "15": "15 - Cantal", "16": "16 - Charente", "17": "17 - Charente-Maritime",
    "18": "18 - Cher", "19": "19 - Corrèze", "2A": "2A - Corse-du-Sud", "2B": "2B - Haute-Corse",
    "21": "21 - Côte-d'Or", "22": "22 - Côtes-d'Armor", "23": "23 - Creuse", "24": "24 - Dordogne",
    "25": "25 - Doubs", "26": "26 - Drôme", "27": "27 - Eure", "28": "28 - Eure-et-Loir", "29": "29 - Finistère",
    "30": "30 - Gard", "31": "31 - Haute-Garonne", "32": "32 - Gers", "33": "33 - Gironde", "34": "34 - Hérault",
    "35": "35 - Ille-et-Vilaine", "36": "36 - Indre", "37": "37 - Indre-et-Loire", "38": "38 - Isère",
    "39": "39 - Jura", "40": "40 - Landes", "41": "41 - Loir-et-Cher", "42": "42 - Loire", "43": "43 - Haute-Loire",
    "44": "44 - Loire-Atlantique", "45": "45 - Loiret", "46": "46 - Lot", "47": "47 - Lot-et-Garonne",
    "48": "48 - Lozère", "49": "49 - Maine-et-Loire", "50": "50 - Manche", "51": "51 - Marne",
    "52": "52 - Haute-Marne", "53": "53 - Mayenne", "54": "54 - Meurthe-et-Moselle", "55": "55 - Meuse",
    "56": "56 - Morbihan", "57": "57 - Moselle", "58": "58 - Nièvre", "59": "59 - Nord", "60": "60 - Oise",
    "61": "61 - Orne", "62": "62 - Pas-de-Calais", "63": "63 - Puy-de-Dôme", "64": "64 - Pyrénées-Atlantiques",
    "65": "65 - Hautes-Pyrénées", "66": "66 - Pyrénées-Orientales", "67": "67 - Bas-Rhin", "68": "68 - Haut-Rhin",
    "69": "69 - Rhône", "70": "70 - Haute-Saône", "71": "71 - Saône-et-Loire", "72": "72 - Sarthe",
    "73": "73 - Savoie", "74": "74 - Haute-Savoie", "75": "75 - Paris", "76": "76 - Seine-Maritime",
    "77": "77 - Seine-et-Marne", "78": "78 - Yvelines", "79": "79 - Deux-Sèvres", "80": "80 - Somme",
    "81": "81 - Tarn", "82": "82 - Tarn-et-Garonne", "83": "83 - Var", "84": "84 - Vaucluse",
    "85": "85 - Vendée", "86": "86 - Vienne", "87": "87 - Haute-Vienne", "88": "88 - Vosges",
    "89": "89 - Yonne", "90": "90 - Territoire de Belfort", "91": "91 - Essonne", "92": "92 - Hauts-de-Seine",
    "93": "93 - Seine-Saint-Denis", "94": "94 - Val-de-Marne", "95": "95 - Val-d'Oise"
}

def get_logo_base64():
    img_path = ROOT / "assets" / "image.png"
    ext = "png"
    if not img_path.exists():
        img_path = ROOT / "assets" / "image.jpg"
        ext = "jpeg"
        if not img_path.exists():
            return ""

    try:
        with open(img_path, "rb") as img_file:
            encoded = base64.b64encode(img_file.read()).decode("ascii")
        return f"data:image/{ext};base64,{encoded}"
    except Exception:
        return ""

LOGO_SRC = get_logo_base64()

import dash
from dash import ALL, ClientsideFunction, ctx, dcc, html, Input, Output, State
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import dash_leaflet as dl
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import json
import re
import threading
import time
from datetime import datetime, timedelta

from lib.db.connection import get_engine
from flask import Response, abort
from lib import circulations, sprites, suivi
from lib.itineraire import FENETRE_API_JOURS, options_heures, retour_minimum, RAYON_POI_KM, chercher_destinations, etiquettes_trajets, options_gares, quand_depuis, rechercher, style_dernier_km, tracer_trajet
from lib.reseau_ferre import charger_reseau

# ==============================================================================
# 2. INITIALISATION & THÈMES
# ==============================================================================
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.FONT_AWESOME],
    suppress_callback_exceptions=True
)
app.title = "MySNCF Experience"

app.index_string = '''
<!DOCTYPE html>
<html lang="fr">
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            :focus-visible {
                outline: 3px solid #c71556 !important;
                outline-offset: 2px !important;
            }
            body {
                overflow-x: hidden;
            }
            .dash-card {
                border-radius: 12px !important;
                box-shadow: 0 6px 18px rgba(0, 0, 0, 0.04) !important;
                border: 1px solid rgba(0,0,0,0.06) !important;
                overflow: hidden;
            }
            .kpi-card {
                border-radius: 12px !important;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03) !important;
                border: 1px solid rgba(0,0,0,0.05) !important;
                border-top-width: 4px !important;
            }
            #tabs-navigation .nav-link {
                color: #4b5563;
                font-weight: 600;
                border-radius: 8px !important;
                padding: 6px 16px;
                margin: 0 4px;
                border: none !important;
                transition: all 0.2s ease;
            }
            #tabs-navigation .nav-link.active {
                background-color: #c71556 !important;
                color: white !important;
            }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''

CARMILLON = "#c71556"
COLORBLIND_PALETTE = ["#377eb8", "#ff7f00", "#1b9e77", "#999999", "#e41a1c"]

THEME_COLORS = {
    "light": {
        "bg": "#f4f6f8", 
        "card_bg": "#ffffff", 
        "text": "#212529",
        "tiles": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "map_class": "", "root_class": "",
    },
    "dark": {
        "bg": "#11151c", 
        "card_bg": "#1a202c", 
        "text": "#f1f1f1",
        "tiles": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "map_class": "carte-sombre", "root_class": "theme-sombre",
    }
}
transition_style = {"transition": "background-color 0.4s ease, color 0.4s ease"}
engine = get_engine()

def get_gares_options():
    try:
        return options_gares(engine)
    except Exception:
        return []

def get_reseau_ferre():
    """Voies ferrées pour coller le tracé des trains, None si le tracé n'est pas en base (le trajet est alors une ligne droite)."""
    try:
        return charger_reseau(engine)
    except Exception:
        return None

reseau_ferre = get_reseau_ferre()

# Les horaires de tous les trains se chargent en arrière-plan (une dizaine de secondes) pour que le bouton « Tous les trains en direct » réponde vite.
threading.Thread(target=lambda: circulations.charger(engine), daemon=True).start()

def get_destinations_options():
    try:
        df_dest = pd.read_sql("SELECT DISTINCT nom FROM lieu WHERE type NOT IN ('arret_bus', 'arret_train') AND nom IS NOT NULL ORDER BY nom LIMIT 2000", engine)
        return [{'label': d, 'value': d} for d in df_dest['nom'].tolist()]
    except Exception:
        return [{'label': d, 'value': d} for d in ["Château de Versailles", "Musée du Louvre", "Gare de Marseille Saint-Charles"]]

def get_departements_options():
    try:
        df_dep = pd.read_sql("SELECT DISTINCT departement FROM lieu WHERE departement IS NOT NULL ORDER BY departement", engine)
        options = []
        for code in df_dep['departement'].tolist():
            code_str = str(code).zfill(2) if str(code).isdigit() and len(str(code)) < 2 else str(code)
            label = DEPARTEMENTS_MAP.get(code_str, DEPARTEMENTS_MAP.get(str(code), str(code)))
            options.append({'label': label, 'value': str(code)})
        return options
    except Exception:
        return [{'label': f"{k} - {v}", 'value': k} for k, v in [("13", "13 - Bouches-du-Rhône"), ("84", "84 - Vaucluse"), ("75", "75 - Paris")]]

TRAINS = ["OUIGO", "TGV INOUI", "TER", "Transilien", "RER", "Renfe AVE", "Frecciarossa"]

custom_spinner = html.Div([
    html.I(className="fa-solid fa-train-subway fa-beat-fade me-3", style={"color": CARMILLON, "fontSize": "2rem"}),
    html.Div("Analyse SQL en cours...", className="mt-2 text-muted fw-bold")
], className="text-center p-3")

# ==============================================================================
# 3. MOTEUR ANALYTIQUE ET REQUÊTES SQL
# ==============================================================================
def get_tab2_data(categorie="tous", regions=None, depart=None, arrivee=None, trains=None):
    try:
        type_filter = "type NOT IN ('gare', 'arret_bus', 'arret_train')"
        if categorie == "culture":
            type_filter = "type IN ('culture', 'tourisme')"
        elif categorie == "evenement":
            type_filter = "type IN ('evenement')"
        elif categorie == "tourisme":
            type_filter = "type IN ('tourisme')"

        conditions = [type_filter]
        if regions:
            if isinstance(regions, list) and len(regions) > 0:
                reg_list = "', '".join([str(r) for r in regions])
                conditions.append(f"departement IN ('{reg_list}')")
            elif isinstance(regions, str):
                conditions.append(f"departement = '{regions}'")

        if arrivee:
            conditions.append(f"nom = '{arrivee}'")

        where_clause = " AND ".join(conditions)

        # 1. Graphe 1 : Volume de sites x IAF par Département
        df_iaf = pd.read_sql(f"""
            SELECT 
                departement as "Departement_Code",
                COUNT(id) as "Nombre_POI",
                ROUND(100.0 * SUM(CASE WHEN distance_gare_km <= 5 THEN 1 ELSE 0 END) / COUNT(id), 1) as "IAF"
            FROM lieu
            WHERE {where_clause} AND departement IS NOT NULL
            GROUP BY departement
            HAVING "Nombre_POI" > 5
        """, engine)

        if not df_iaf.empty:
            df_iaf['Departement_Nom'] = df_iaf['Departement_Code'].apply(
                lambda x: DEPARTEMENTS_MAP.get(str(x).zfill(2) if str(x).isdigit() and len(str(x)) < 2 else str(x), str(x))
            )
        else:
            raise Exception("Données BDD absentes")

        # 2. Graphe 3 : Répartition des tranches de distance
        df_distance = pd.read_sql(f"""
            SELECT 
                CASE 
                    WHEN distance_gare_km <= 1.5 THEN '≤ 1,5 km (Pied)'
                    WHEN distance_gare_km <= 5 THEN '1,5-5 km (Vélo/Bus)'
                    WHEN distance_gare_km <= 15 THEN '5-15 km (Navette)'
                    ELSE '> 15 km (Voiture)'
                END as "Tranche",
                type as "Categorie",
                COUNT(id) as "Nombre"
            FROM lieu 
            WHERE distance_gare_km IS NOT NULL AND {where_clause}
            GROUP BY 1, 2
        """, engine)

        # 3. Graphe 4 : Saisonnalité Événementielle
        df_saison = pd.read_sql("""
            SELECT 
                CASE CAST(STRFTIME('%m', ep.date_debut) AS INTEGER)
                    WHEN 1 THEN 'Jan' WHEN 2 THEN 'Fév' WHEN 3 THEN 'Mar' WHEN 4 THEN 'Avr'
                    WHEN 5 THEN 'Mai' WHEN 6 THEN 'Juin' WHEN 7 THEN 'Juil' WHEN 8 THEN 'Août'
                    WHEN 9 THEN 'Sept' WHEN 10 THEN 'Oct' WHEN 11 THEN 'Nov' ELSE 'Déc'
                END as "Mois",
                COUNT(e.id) as "Evenements"
            FROM evenement e
            JOIN evenement_periode ep ON ep.evenement_id = e.id
            GROUP BY "Mois"
            ORDER BY ep.date_debut ASC
        """, engine)

        # 4. KPIs Métier
        stats_kpi = pd.read_sql(f"""
            SELECT 
                COUNT(id) as total_sites,
                SUM(CASE WHEN distance_gare_km <= 5 THEN 1 ELSE 0 END) as sites_5km,
                SUM(CASE WHEN distance_gare_km > 15 OR distance_gare_km IS NULL THEN 1 ELSE 0 END) as sites_blancs
            FROM lieu
            WHERE {where_clause}
        """, engine).iloc[0]

        total = stats_kpi['total_sites'] or 1
        sites_5km = stats_kpi['sites_5km'] or 0
        sites_blancs = stats_kpi['sites_blancs'] or 0

        couverture_pct = round(((total - sites_blancs) / total) * 100, 1)
        blanches_pct = round((sites_blancs / total) * 100, 1)

        return df_iaf, df_distance, df_saison, f"{couverture_pct} %", f"{sites_5km:,}".replace(",", " "), f"{blanches_pct} %"

    except Exception:
        mock_iaf = pd.DataFrame({
            "Departement_Code": ["75", "92", "93", "78", "67", "13", "64", "36", "61", "56", "47", "40", "23", "29", "53", "04", "85", "32", "07"],
            "Departement_Nom": ["Paris", "Hauts-de-Seine", "Seine-Saint-Denis", "Yvelines", "Bas-Rhin", "Bouches-du-Rhône", "Pyrénées-Atlantiques", "Indre (36)", "Orne (61)", "Morbihan (56)", "Lot-et-Garonne (47)", "Landes (40)", "Creuse (23)", "Finistère (29)", "Mayenne (53)", "Alpes-de-Haute-Provence (04)", "Vendée (85)", "Gers (32)", "Ardèche (07)"],
            "Nombre_POI": [2500, 1200, 1100, 1500, 1800, 2200, 1300, 290, 340, 620, 410, 530, 280, 780, 310, 390, 680, 320, 450],
            "IAF": [81.5, 74.0, 73.0, 67.0, 55.0, 47.5, 45.0, 26.1, 22.8, 23.2, 23.1, 22.7, 21.0, 20.3, 19.3, 18.2, 16.8, 15.1, 14.2]
        })
        mock_dist = pd.DataFrame({"Tranche": ["≤ 1,5 km (Pied)", "1,5-5 km (Vélo/Bus)"], "Categorie": ["Culture", "Tourisme"], "Nombre": [150, 100]})
        mock_saison = pd.DataFrame({"Mois": ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sept", "Oct", "Nov", "Déc"], "Evenements": [15, 8, 9, 12, 30, 80, 150, 110, 25, 20, 10, 8]})
        return mock_iaf, mock_dist, mock_saison, "82.4 %", "14 530", "17.6 %"

def get_decision_df(regions=None, mode="pires"):
    try:
        where_reg = ""
        if regions:
            if isinstance(regions, list) and len(regions) > 0:
                reg_list = "', '".join([str(r) for r in regions])
                where_reg = f"AND l.departement IN ('{reg_list}')"
            elif isinstance(regions, str):
                where_reg = f"AND l.departement = '{regions}'"

        order_by = "DESC" if mode == "pires" else "ASC"

        query = f"""
            SELECT 
                l.nom as "SITE TOURISTIQUE",
                COALESCE(g.nom, 'Gare inconnue') || ' (' || ROUND(l.distance_gare_km, 1) || ' km)' as "GARE LA + PROCHE",
                CASE 
                    WHEN l.distance_gare_km <= 1.5 THEN 'Piéton / VLS'
                    WHEN l.distance_gare_km <= 5 THEN 'Bus / Navette'
                    ELSE 'Voiture requise'
                END as "DERNIER KM",
                CASE 
                    WHEN l.distance_gare_km > 15 THEN 'Urgente'
                    WHEN l.distance_gare_km > 5 THEN 'Élevée'
                    WHEN l.distance_gare_km > 1.5 THEN 'Moyenne'
                    ELSE 'Excellente'
                END as "PRIORITÉ"
            FROM lieu l
            LEFT JOIN lieu g ON l.gare_proche_id = g.id
            WHERE l.type NOT IN ('gare', 'arret_bus', 'arret_train') AND l.distance_gare_km IS NOT NULL {where_reg}
            ORDER BY l.distance_gare_km {order_by}
            LIMIT 10
        """
        df_table = pd.read_sql(query, engine)
        if df_table.empty:
            raise Exception("Vide")
        return df_table
    except Exception:
        return pd.DataFrame({
            "SITE TOURISTIQUE": ["Grotte Chauvet 2 (07)", "Château de Chambord (41)", "Site Antique de Vaison (84)", "Clisson (44)"],
            "GARE LA + PROCHE": ["Montélimar (38 km)", "Blois (16 km)", "Orange (27 km)", "Gare de Clisson (1.2 km)"],
            "DERNIER KM": ["Aucun car", "Navette saison", "Voiture requise", "Piéton / Navette"],
            "PRIORITÉ": ["Urgente", "Moyenne", "Élevée", "Excellente"]
        })

def generate_decision_table(theme="light", regions=None, mode="pires"):
    is_dark = theme == "dark"
    df_table = get_decision_df(regions, mode)
    
    def get_badge(prio):
        if prio == "Urgente":
            return dbc.Badge(prio, color="danger")
        elif prio == "Élevée":
            return dbc.Badge(prio, color="warning", className="text-dark fw-bold")
        elif prio == "Moyenne":
            return dbc.Badge(prio, color="info")
        else:
            return dbc.Badge(prio, color="success")

    rows = [html.Tr([html.Td(row["SITE TOURISTIQUE"], style={"fontWeight": "bold"}), html.Td(row["GARE LA + PROCHE"]), html.Td(row["DERNIER KM"]), html.Td(get_badge(row["PRIORITÉ"]))]) for _, row in df_table.iterrows()]
    table = dbc.Table([html.Thead(html.Tr([html.Th(col) for col in df_table.columns])), html.Tbody(rows)], striped=True, bordered=False, hover=True, color="dark" if is_dark else "light")
    return table

# ==============================================================================
# 4. LAYOUT DE L'APPLICATION (SINGLE SCREEN)
# ==============================================================================
HAUTEUR_CARTE = "max(640px, calc(100vh - 240px))"      # toute la hauteur de l'écran sous les KPI, pour ne pas avoir à descendre
# Panneau des trajets (par-dessus la carte, à droite du panneau de recherche) et bouton pour le rouvrir.
STYLE_PANNEAU = {"position": "absolute", "top": "16px", "right": "16px", "width": "300px", "maxHeight": "calc(100% - 32px)", "overflowY": "auto", "zIndex": "1000",
                 "borderRadius": "15px", "boxShadow": "0px 4px 15px rgba(0,0,0,0.3)"}
STYLE_OUVRIR = {"position": "absolute", "top": "16px", "right": "16px", "zIndex": "1000", "backgroundColor": CARMILLON, "border": "none", "fontWeight": "bold",
                "boxShadow": "0px 4px 15px rgba(0,0,0,0.3)"}
init_colors = THEME_COLORS["light"]
gares_opts = get_gares_options()
destinations_opts = get_destinations_options()
departements_opts = get_departements_options()
hours_opts = options_heures(None, None)

def mise_en_page():
    """Reconstruite à chaque ouverture de la page : les dates par défaut sont celles du jour, pas celles du démarrage du serveur."""
    return dbc.Container(id="main-container", style={"backgroundColor": init_colors["bg"], "color": init_colors["text"], "minHeight": "100vh", "padding": "12px 20px", **transition_style}, fluid=True, children=[
        dcc.Download(id="download-export"),
        dcc.Store(id="store-selected-dept", data=None),
        dcc.Store(id="store-resultat"),
        dcc.Store(id="store-selection", data={"sens": "aller", "index": 0}),
        dcc.Store(id="store-etapes"),
        dcc.Store(id="store-horloge", data={"mode": "reel"}),
        dcc.Store(id="store-js"),
        dcc.Store(id="store-js-centre"),
        dcc.Store(id="store-tous", data={"actif": False, "trains": []}),
        dcc.Store(id="store-js-tous"),
        dcc.Store(id="store-pas"),
        dcc.Store(id="store-js-pas"),
        dcc.Store(id="store-js-onglet"),
        dcc.Interval(id="tick-tous", interval=120_000),
        dcc.Interval(id="tick", interval=1000),
    
        # MODAL DETAILS-ON-DEMAND (POP-UP TABLEAU TOP 10)
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle("🎯 Plan d'Action Opérationnel : Top 10 des Sites", className="fw-bold")),
            dbc.ModalBody([
                dbc.Row(className="align-items-center mb-3", children=[
                    dbc.Col(html.Span("Hiérarchisation stratégique du besoin en équipements et navettes", className="text-muted small"), width=6),
                    dbc.Col(
                        dbc.RadioItems(
                            id="t2-table-mode",
                            options=[
                                {"label": "🚨 10 zones prioritaires à équiper", "value": "pires"},
                                {"label": "🏆 10 gares modèles d'accessibilité", "value": "meilleurs"}
                            ],
                            value="pires",
                            inline=True,
                            className="fw-bold d-flex justify-content-end"
                        ),
                        width=6
                    )
                ]),
                html.Div(id="table-container")
            ]),
            dbc.ModalFooter(
                dbc.Button("Fermer", id="btn-close-modal", style={"backgroundColor": CARMILLON, "border": "none", "fontWeight": "bold"}, n_clicks=0)
            )
        ], id="modal-plan-action", size="xl", is_open=False),

        # BANDEAU UNIFIÉ UNIQUE (LOGO + ONGLETS À GAUCHE)
        dbc.Row(id="top-bar", style={"backgroundColor": init_colors["card_bg"], "borderRadius": "12px", **transition_style}, className="px-3 py-2 mb-3 shadow-sm align-items-center justify-content-between", children=[
            dbc.Col(
                html.Div([
                    html.Img(id="logo-img", src=LOGO_SRC, alt="Logo MySNCF Experience", style={"maxHeight": "100px", "objectFit": "contain", "borderRadius": "6px", "padding": "2px", "marginRight": "15px"}),
                    dbc.Tabs(
                        id="tabs-navigation",
                        active_tab="tab-2",
                        className="nav-pills border-0 d-inline-flex",
                        children=[
                            dbc.Tab(label="Itinéraire Voyageur", tab_id="tab-1", tab_style={"cursor": "pointer"}),
                            dbc.Tab(label="Analyse de la couverture ferroviaire", tab_id="tab-2", tab_style={"cursor": "pointer"}),
                        ]
                    ),
                ], className="d-flex align-items-center"),
                width="auto"
            ),
            dbc.Col(
                dbc.Checklist(options=[{"label": "☀️ Clair / 🌙 Sombre", "value": "dark"}], value=[], id="theme-switch", switch=True, className="fw-bold d-flex justify-content-end mb-0"),
                width="auto"
            ),
        ]),

        # CONTENU DE L'ONGLET 1 (ITINÉRAIRE)
        html.Div(id="tab-1-content", style={"display": "none"}, children=[
            dbc.Row([
                dbc.Col(dbc.Card(id="card-kpi-dist", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "border": "none", **transition_style}, children=[dbc.CardBody([
                    html.H6("Distance Gare -> Destination", style={"opacity": 0.8}), html.H3(id="kpi-distance", children="-- km", style={"color": COLORBLIND_PALETTE[2]}), html.Small(id="kpi-distance-detail", style={"opacity": 0.7})
                ])]), width=4),
                dbc.Col(dbc.Card(id="card-kpi-trans", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "border": "none", **transition_style}, children=[dbc.CardBody([
                    html.H6("Transport 1er/Dernier km", style={"opacity": 0.8}), html.H3(id="kpi-intermodal", children="--", style={"color": COLORBLIND_PALETTE[1]}), html.Small(id="kpi-intermodal-detail", style={"opacity": 0.7})
                ])]), width=4),
                dbc.Col(dbc.Card(id="card-kpi-statut", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "border": "none", **transition_style}, children=[dbc.CardBody([
                    html.H6("Faisabilité Décarbonée", style={"opacity": 0.8}), html.H3(id="kpi-statut", children="--", style={"color": COLORBLIND_PALETTE[0]}), html.Small(id="kpi-statut-detail", style={"opacity": 0.7})
                ])]), width=4),
            ], className="mb-4"),

            dbc.Row([
                dbc.Col([
                    dbc.Card(id="card-map", style={"border": "none", "backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "height": HAUTEUR_CARTE, "position": "relative", "overflow": "hidden", **transition_style}, children=[
                        dcc.Loading(custom_spinner=custom_spinner, target_components={"map-lines": "children", "map-isochrones": "children", "map-markers": "children"}, children=[
                            html.Div(style={"position": "relative"}, children=[
                                        
                                # PANNEAU RECHERCHE FLOTTANT (Onglet 1)
                                html.Div(id="search-panel", style={
                                    "position": "absolute", "top": "20px", "left": "20px", "zIndex": "1000",
                                    "backgroundColor": init_colors["card_bg"], "color": init_colors["text"],
                                    "padding": "20px", "borderRadius": "15px", "boxShadow": "0px 4px 15px rgba(0,0,0,0.2)",
                                    "width": "340px", **transition_style
                                }, children=[
                                    html.H5(html.I(className="fa-solid fa-route me-2"), className="mb-2", style={"color": CARMILLON}),
                                            
                                    html.Label("Départ :", className="fw-bold mb-1", style={"fontSize": "0.9rem"}),
                                    dcc.Dropdown(id="input-depart", options=gares_opts, placeholder="Gare de départ...", searchable=True, className="mb-2"),
                                            
                                    html.Label("Destination :", className="fw-bold mb-1", style={"fontSize": "0.9rem"}),
                                    dcc.Dropdown(id="input-arrivee", placeholder="Rechercher un lieu...", searchable=True, search_order="original", className="mb-2"),   # garde l'ordre du serveur : ville, ses événements, le reste
                                            
                                    html.Label("Aller :", className="fw-bold mb-1", style={"fontSize": "0.9rem"}),
                                    dbc.Row(className="g-2 mb-2", children=[
                                        dbc.Col(dcc.DatePickerSingle(id="date-picker-aller", date=date.today(), min_date_allowed=date.today(), max_date_allowed=date.today() + timedelta(days=FENETRE_API_JOURS), display_format="DD/MM/YYYY"), width=7),
                                        dbc.Col(dcc.Dropdown(id="time-picker-aller", options=hours_opts, placeholder="Heure"), width=5),
                                    ]),
                                            
                                    dbc.Checklist(options=[{"label": "Trajet Aller/Retour", "value": 1}], value=[], id="switch-ar", switch=True, className="fw-bold mb-2", style={"fontSize": "0.9rem"}),
                                            
                                    html.Div(id="row-retour", style={"display": "none"}, children=[
                                        html.Label("Retour :", className="fw-bold mb-1", style={"fontSize": "0.9rem"}),
                                        dbc.Row(className="g-2 mb-2", children=[
                                            dbc.Col(dcc.DatePickerSingle(id="date-picker-retour", min_date_allowed=date.today(), max_date_allowed=date.today() + timedelta(days=FENETRE_API_JOURS), display_format="DD/MM/YYYY", placeholder="Date retour"), width=7),
                                            dbc.Col(dcc.Dropdown(id="time-picker-retour", options=hours_opts, placeholder="Heure"), width=5),
                                        ])
                                    ]),
                                            
                                    html.Hr(className="my-2", style={"opacity": "0.1"}),
                                            
                                    html.Label("Catégorie :", className="fw-bold mb-1", style={"fontSize": "0.9rem"}),
                                    dbc.RadioItems(
                                        id="filter-categorie",
                                        options=[
                                            {"label": html.Span([html.I(className="fa-solid fa-map-location-dot me-2"), "Toutes"]), "value": "tous"},
                                            {"label": html.Span([html.I(className="fa-solid fa-landmark me-2"), "Musées"]), "value": "culture"},
                                            {"label": html.Span([html.I(className="fa-solid fa-camera me-2"), "Tourisme"]), "value": "tourisme"},
                                            {"label": html.Span([html.I(className="fa-solid fa-masks-theater me-2"), "Festivals"]), "value": "evenement"}
                                        ],
                                        value="tous", inline=True, className="fw-bold mb-3", style={"fontSize": "0.85rem"}
                                    ),
                                            
                                    dbc.Button([html.I(className="fa-solid fa-magnifying-glass me-2"), "Rechercher"], id="btn-search", style={"backgroundColor": CARMILLON, "border": "none", "width": "100%", "fontWeight": "bold", "padding": "10px"}),
                                    dbc.Button([html.I(className="fa-solid fa-train-subway me-2"), html.Span("Tous les trains en direct", id="btn-tous-texte")], id="btn-tous",
                                               color="secondary", outline=True, className="w-100 mt-2", style={"fontWeight": "bold", "fontSize": "0.9rem"}),
                                ]),

                                # TRAJETS PROPOSÉS, par-dessus la carte : un bloc cliquable par option, Aller / Retour, avec un bouton pour fermer et rouvrir
                                dbc.Button([html.I(className="fa-solid fa-route me-2"), "Afficher les trajets"], id="btn-ouvrir", style={**STYLE_OUVRIR, "display": "none"}),
                                html.Div(id="panneau-resultats", style={**STYLE_PANNEAU, "display": "none"}, children=[
                                    dbc.Card(id="card-results", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "border": "none", **transition_style}, children=[dbc.CardBody([
                                        html.Div(className="d-flex flex-wrap align-items-center gap-2 mb-2", children=[
                                            html.H6(id="results-title", children="Trajets proposés", className="mb-0 fw-bold", style={"display": "none"}),            # titre masqué : la carte et les horaires suffisent (l'Output reste, il est alimenté par le callback)
                                            html.Div(dbc.RadioItems(id="sens", options=[{"label": "Aller", "value": "aller"}, {"label": "Retour", "value": "retour"}], value="aller", inline=True,
                                                                    className="btn-group", inputClassName="btn-check", labelClassName="btn btn-outline-secondary btn-sm", labelCheckedClassName="active"),
                                                     id="col-sens", style={"display": "none"}),
                                            dbc.Button(html.I(className="fa-solid fa-xmark"), id="btn-fermer", color="light", size="sm", className="ms-auto", title="Masquer les trajets"),
                                        ]),
                                        html.Div(className="d-flex flex-wrap align-items-center gap-2 mb-2", children=[
                                            dbc.Button([html.I(className="fa-solid fa-play me-2"), "Simuler"], id="btn-sim", color="secondary", outline=True, size="sm", title="Simuler le trajet"),
                                            dbc.Button(html.I(className="fa-solid fa-crosshairs"), id="btn-centrer", color="secondary", outline=True, size="sm",
                                                       title="Centrer la carte sur le train (en temps réel, ou simulé)"),
                                            html.Div(id="suivi-etat", style={"fontSize": "0.75rem", "opacity": 0.8, "width": "100%"}),
                                        ]),
                                        html.Div(id="poi-legend", className="mb-2"),
                                        dcc.Loading(type="circle", color=CARMILLON, children=html.Div(id="options-trajets", children=html.Div("Choisissez une gare de départ et une destination, puis lancez la recherche.", className="text-muted"))),
                                    ])]),
                                ]),

                                dl.Map(id="map", center=[46.2, 3.5], zoom=5, style={"width": "100%", "height": HAUTEUR_CARTE, "display": "block", "margin": "0"}, children=[
                                    dl.TileLayer(id="map-tiles", url=init_colors["tiles"]),
                                    dl.LayerGroup(id="map-lines"), dl.LayerGroup(id="map-isochrones"), dl.LayerGroup(id="map-markers")
                                ])
                            ])
                        ])
                    ])
                ], width=12)
            ]),
        ]),

        # CONTENU DE L'ONGLET 2 (ANALYSE SCNF - SINGLE SCREEN)
        html.Div(id="tab-2-content", style={"display": "block"}, children=[
            # BARRE DE RECHERCHE & FILTRES
            dbc.Card(id="tab2-search-bar", className="dash-card mb-3", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], **transition_style}, children=[
                dbc.CardBody(className="py-2 px-3", children=[
                    dbc.Row(className="g-2 align-items-end", children=[
                        dbc.Col([
                            html.Label([html.I(className="fa-solid fa-location-dot me-1"), "Départ"], htmlFor="t2-depart", className="fw-bold mb-1", style={"fontSize": "0.8rem"}),
                            dcc.Dropdown(options=gares_opts, placeholder="Départ...", searchable=True, id="t2-depart")
                        ], width=2),
                    
                        dbc.Col([
                            html.Label([html.I(className="fa-solid fa-flag-checkered me-1"), "Destination"], htmlFor="t2-arrivee", className="fw-bold mb-1", style={"fontSize": "0.8rem"}),
                            dcc.Dropdown(options=destinations_opts, placeholder="Destination...", searchable=True, id="t2-arrivee")
                        ], width=2),
                    
                        dbc.Col([
                            html.Label([html.I(className="fa-solid fa-map me-1"), "Région / Dép."], htmlFor="t2-region", className="fw-bold mb-1", style={"fontSize": "0.8rem"}),
                            dcc.Dropdown(options=departements_opts, placeholder="Toutes...", id="t2-region", multi=True)
                        ], width=3),
                    
                        dbc.Col([
                            html.Label([html.I(className="fa-regular fa-calendar-days me-1"), "Période"], htmlFor="t2-periode-range", className="fw-bold mb-1", style={"fontSize": "0.8rem"}),
                            html.Div(dcc.DatePickerRange(
                                id="t2-periode-range",
                                start_date=date.today(),
                                end_date=date.today(),
                                display_format="DD/MM/YYYY",
                                start_date_placeholder_text="Du",
                                end_date_placeholder_text="Au"
                            ), style={"width": "100%"})
                        ], width=3),
                    
                        dbc.Col([
                            html.Label([html.I(className="fa-solid fa-train me-1"), "Type de train"], htmlFor="t2-train", className="fw-bold mb-1", style={"fontSize": "0.8rem"}),
                            dcc.Dropdown(options=[{'label': t, 'value': t} for t in TRAINS], placeholder="Tous...", id="t2-train", multi=True)
                        ], width=2),
                    ]),
                    dbc.Row(className="mt-2 align-items-center", children=[
                        dbc.Col(
                            html.Div([
                                html.Span(id="drilldown-text", children="💡 Cliquez sur un point du Graphe 1 pour zoomer (Drill-down)", className="text-muted small italic me-2"),
                                dbc.Button("✖ Réinitialiser le filtre", id="btn-reset-drilldown", color="danger", size="sm", outline=True, style={"display": "none", "fontSize": "0.75rem", "padding": "2px 8px"}, n_clicks=0)
                            ], id="drilldown-status", className="d-flex align-items-center"),
                            width=8, className="text-start"
                        ),
                        dbc.Col(
                            dbc.Button([html.I(className="fa-solid fa-filter me-2"), "Filtrer"], id="btn-search-t2", style={"backgroundColor": CARMILLON, "border": "none", "fontWeight": "bold", "padding": "6px 20px", "borderRadius": "6px", "fontSize": "0.85rem"}),
                            width=4, className="text-end"
                        )
                    ])
                ])
            ]),

            # KPIS
            dcc.Loading(custom_spinner=custom_spinner, children=[
                html.Div(id="t2-content", children=[
                    dbc.Row(className="g-3 mb-3", children=[
                        dbc.Col(dbc.Card(id="card-kpi-global-1", className="kpi-card", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "borderTopColor": "#10b981", **transition_style}, children=[dbc.CardBody(className="py-2 px-3", children=[
                            html.Div([
                                html.H6("Taux de couverture (< 5km)", className="text-uppercase text-muted fw-bold m-0 me-1", style={"fontSize": "0.7rem"}),
                                html.I(className="fa-solid fa-circle-info text-muted", id="tooltip-kpi-1-target", style={"fontSize": "0.75rem", "cursor": "pointer"}),
                                dbc.Tooltip("Pourcentage de sites touristiques situés à moins de 5 km d'une gare SNCF.", target="tooltip-kpi-1-target", placement="top")
                            ], className="d-flex align-items-center mb-1"),
                            html.H4(id="t2-kpi-couverture", children="82.4 %", style={"color": "#10b981", "fontWeight": "bold", "margin": "0"})
                        ])]), width=4),
                    
                        dbc.Col(dbc.Card(id="card-kpi-global-2", className="kpi-card", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "borderTopColor": COLORBLIND_PALETTE[1], **transition_style}, children=[dbc.CardBody(className="py-2 px-3", children=[
                            html.Div([
                                html.H6("Sites accessibles sans voiture", className="text-uppercase text-muted fw-bold m-0 me-1", style={"fontSize": "0.7rem"}),
                                html.I(className="fa-solid fa-circle-info text-muted", id="tooltip-kpi-2-target", style={"fontSize": "0.75rem", "cursor": "pointer"}),
                                dbc.Tooltip("Nombre total de POI directement reliés par la marche, le vélo ou les transports urbains.", target="tooltip-kpi-2-target", placement="top")
                            ], className="d-flex align-items-center mb-1"),
                            html.H4(id="t2-kpi-sites", children="14 530", style={"color": COLORBLIND_PALETTE[1], "fontWeight": "bold", "margin": "0"})
                        ])]), width=4),
                    
                        dbc.Col(dbc.Card(id="card-kpi-global-3", className="kpi-card", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "borderTopColor": CARMILLON, **transition_style}, children=[dbc.CardBody(className="py-2 px-3", children=[
                            html.Div([
                                html.H6("Zones Blanches (> 15km gare)", className="text-uppercase text-muted fw-bold m-0 me-1", style={"fontSize": "0.7rem"}),
                                html.I(className="fa-solid fa-circle-info text-muted", id="tooltip-kpi-3-target", style={"fontSize": "0.75rem", "cursor": "pointer"}),
                                dbc.Tooltip("Pourcentage de sites très éloignés des gares nécessitant une navette dédiée ou une voiture.", target="tooltip-kpi-3-target", placement="top")
                            ], className="d-flex align-items-center mb-1"),
                            html.H4(id="t2-kpi-blanches", children="17.6 %", style={"color": CARMILLON, "fontWeight": "bold", "margin": "0"})
                        ])]), width=4),
                    ]),

                    # DISPOSITION RANGÉE : GRAPHE 1 À GAUCHE, GRAPHES 3 & 4 À DROITE
                    dbc.Row(className="g-3 mb-3", children=[
                        # COLONNE GAUCHE : GRAPHE 1
                        dbc.Col([
                            dbc.Card(id="card-g1", className="dash-card p-2", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], **transition_style}, children=[
                                html.Div(
                                    role="region",
                                    children=[dcc.Graph(id="graph-1", style={"height": "480px"})],
                                    **{"aria-label": "Volume de sites x accessibilité ferroviaire, par département"}
                                )
                            ])
                        ], width=6),
                    
                        # COLONNE DROITE : GRAPHE 3 & 4 EMPILÉS
                        dbc.Col([
                            dbc.Card(id="card-g3", className="dash-card p-2 mb-3", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], **transition_style}, children=[
                                html.Div(
                                    role="region",
                                    children=[dcc.Graph(id="graph-3", style={"height": "225px"})],
                                    **{"aria-label": "Répartition des sites par tranche de distance"}
                                )
                            ]),
                            dbc.Card(id="card-g4-saison", className="dash-card p-2", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], **transition_style}, children=[
                                html.Div(
                                    role="region",
                                    children=[dcc.Graph(id="graph-4", style={"height": "225px"})],
                                    **{"aria-label": "Saisonnalité de la demande événementielle par mois"}
                                )
                            ])
                        ], width=6)
                    ]),

                    # RANGÉE BASSE DE PILOTAGE : BOUTON PLAN D'ACTION + EXPORT DE RAPPORT
                    dbc.Row(className="g-3", children=[
                        dbc.Col(
                            dbc.Card(id="card-outils", className="dash-card p-2 px-3", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], **transition_style}, children=[
                                dbc.Row(className="align-items-center", children=[
                                    dbc.Col([
                                        html.H6([html.I(className="fa-solid fa-sliders me-2", style={"color": CARMILLON}), "Outils d'Aide à la Décision"], className="fw-bold m-0 text-uppercase", style={"fontSize": "0.85rem"}),
                                        html.Small("Consultez la feuille de route opérationnelle ou téléchargez la synthèse stratégique.", className="text-muted")
                                    ], width=6),
                                    dbc.Col([
                                        dbc.Button([html.I(className="fa-solid fa-list-check me-2"), "🎯 Plan d'Action (Top 10)"], id="btn-open-modal", style={"backgroundColor": CARMILLON, "border": "none", "fontWeight": "bold", "fontSize": "0.85rem", "marginRight": "10px"}, n_clicks=0),
                                        dbc.Tooltip("Ouvre la matrice décisionnelle complète détaillant les gares et sites prioritaires.", target="btn-open-modal", placement="top"),
                                    
                                        dbc.Button([html.I(className="fa-solid fa-file-arrow-down me-2"), "📄 Exporter le Rapport"], id="btn-export-report", color="dark", outline=True, style={"fontWeight": "bold", "fontSize": "0.85rem"}, n_clicks=0),
                                        dbc.Tooltip("Télécharge un rapport synthétique au format HTML (imprimable en PDF) incluant les KPIs et le plan d'action.", target="btn-export-report", placement="top")
                                    ], width=6, className="d-flex justify-content-end align-items-center")
                                ])
                            ]),
                            width=12
                        )
                    ])
                ])
            ])
        ])
    ])


app.layout = mise_en_page

# ==============================================================================
# 5. CALLBACKS
# ==============================================================================
@app.callback(
    Output("download-export", "data"),
    Input("btn-export-report", "n_clicks"),
    [State("t2-region", "value"), State("filter-categorie", "value"), State("t2-kpi-couverture", "children"), State("t2-kpi-sites", "children"), State("t2-kpi-blanches", "children")],
    prevent_initial_call=True
)
def export_report(n_clicks, regions, categorie, kpi_couv, kpi_sites, kpi_blanc):
    if not n_clicks:
        return dash.no_update
    
    dept_label = "National (Toute la France)"
    if regions:
        dept_label = ", ".join([DEPARTEMENTS_MAP.get(str(r).zfill(2), str(r)) for r in (regions if isinstance(regions, list) else [regions])])
    
    df_table = get_decision_df(regions, mode="pires")
    table_rows_html = "".join([
        f"<tr><td style='padding:10px;border-bottom:1px solid #eee;'><b>{r['SITE TOURISTIQUE']}</b></td><td style='padding:10px;border-bottom:1px solid #eee;'>{r['GARE LA + PROCHE']}</td><td style='padding:10px;border-bottom:1px solid #eee;'>{r['DERNIER KM']}</td><td style='padding:10px;border-bottom:1px solid #eee;color:#c71556;'><b>{r['PRIORITÉ']}</b></td></tr>"
        for _, r in df_table.iterrows()
    ])
    
    html_content = f"""<!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="utf-8">
        <title>Rapport d'Analyse Métier SNCF</title>
        <style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 40px; color: #212529; background: #f8f9fa; }}
            .header {{ background: #c71556; color: white; padding: 25px; border-radius: 10px; margin-bottom: 30px; }}
            .kpi-container {{ display: flex; gap: 20px; margin-bottom: 30px; }}
            .kpi-box {{ flex: 1; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); border-top: 5px solid #c71556; }}
            .kpi-title {{ font-size: 0.8rem; text-transform: uppercase; color: #6c757d; font-weight: bold; }}
            .kpi-value {{ font-size: 2rem; font-weight: bold; margin-top: 5px; color: #11151c; }}
            table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 10px rgba(0,0,0,0.05); margin-top: 15px; }}
            th {{ background: #343a40; color: white; padding: 12px; text-align: left; font-size: 0.85rem; text-transform: uppercase; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1 style="margin:0; font-size: 1.8rem;">MySNCF Experience — Rapport Métier d'Accessibilité</h1>
            <p style="margin:8px 0 0 0; opacity: 0.9; font-size: 1rem;">Périmètre : {dept_label} | Édité le : {date.today().strftime('%d/%m/%Y')}</p>
        </div>
        
        <h2 style="font-size: 1.2rem; color: #495057;">Chiffres Clés d'Accessibilité Ferroviaire</h2>
        <div class="kpi-container">
            <div class="kpi-box" style="border-top-color: #10b981;">
                <div class="kpi-title">Taux de couverture (< 5km)</div>
                <div class="kpi-value" style="color: #10b981;">{kpi_couv}</div>
            </div>
            <div class="kpi-box" style="border-top-color: #ff7f00;">
                <div class="kpi-title">Sites accessibles sans voiture</div>
                <div class="kpi-value" style="color: #ff7f00;">{kpi_sites}</div>
            </div>
            <div class="kpi-box" style="border-top-color: #c71556;">
                <div class="kpi-title">Zones Blanches (> 15km gare)</div>
                <div class="kpi-value" style="color: #c71556;">{kpi_blanc}</div>
            </div>
        </div>
        
        <h2 style="font-size: 1.2rem; color: #495057;">Plan d'Action Opérationnel — Top 10 des Zones Prioritaires</h2>
        <table>
            <thead>
                <tr>
                    <th>Site Touristique</th>
                    <th>Gare la plus proche</th>
                    <th>Dernier Kilomètre</th>
                    <th>Priorité d'Équipement</th>
                </tr>
            </thead>
            <tbody>
                {table_rows_html}
            </tbody>
        </table>
    </body>
    </html>
    """
    return dcc.send_string(html_content, filename=f"Rapport_SNCF_Accessibilite_{date.today().strftime('%Y%m%d')}.html")

@app.callback(
    [Output("tab-1-content", "style"), Output("tab-2-content", "style")],
    Input("tabs-navigation", "active_tab")
)
def switch_tab_content(active_tab):
    if active_tab == "tab-1":
        return {"display": "block"}, {"display": "none"}
    return {"display": "none"}, {"display": "block"}

# La carte est créée dans l'onglet caché : elle recalcule sa taille quand on ouvre l'onglet Itinéraire (src/assets/trains.js).
app.clientside_callback(
    ClientsideFunction(namespace="trains", function_name="afficherOnglet"),
    Output("store-js-onglet", "data"),
    Input("tabs-navigation", "active_tab")
)

# Au chargement, l'interrupteur de thème se règle sur le mode clair / sombre du système (src/assets/trains.js).
app.clientside_callback(
    ClientsideFunction(namespace="trains", function_name="themeSysteme"),
    Output("theme-switch", "value"),
    Input("theme-switch", "id")
)

@app.callback(
    Output("modal-plan-action", "is_open"),
    [Input("btn-open-modal", "n_clicks"), Input("btn-close-modal", "n_clicks")],
    [State("modal-plan-action", "is_open")]
)
def toggle_modal(n1, n2, is_open):
    if n1 or n2:
        return not is_open
    return is_open

@app.callback(Output("row-retour", "style"), Input("switch-ar", "value"))
def toggle_return_fields(ar_checked):
    return {"display": "block"} if ar_checked and 1 in ar_checked else {"display": "none"}

def _jour(texte):
    return date.fromisoformat(str(texte)[:10]) if texte else None


def _quand_aller(jour, heure):
    """Départ de l'aller d'après le formulaire (maintenant si le jour est aujourd'hui sans heure, 8 h sinon)."""
    return quand_depuis(jour, heure) if jour else None


@app.callback(
    [Output("time-picker-aller", "options"), Output("time-picker-aller", "value")],
    Input("date-picker-aller", "date"),
    State("time-picker-aller", "value")
)
def heures_aller(jour, heure):
    """Les heures déjà passées aujourd'hui sont grisées."""
    options = options_heures(_jour(jour), datetime.now())
    return options, (None if any(o["disabled"] and o["value"] == heure for o in options) else heure)


@app.callback(
    [Output("date-picker-retour", "date"), Output("date-picker-retour", "min_date_allowed"), Output("date-picker-retour", "max_date_allowed")],
    [Input("date-picker-aller", "date"), Input("time-picker-aller", "value"), Input("date-picker-aller", "max_date_allowed")],
    State("date-picker-retour", "date")
)
def calendrier_retour(jour, heure, maxi, retour):
    """Le retour ne peut pas précéder l'aller (ni dépasser la fenêtre de l'API SNCF)."""
    aller = _quand_aller(_jour(jour), heure)
    mini = retour_minimum(aller).date() if aller else date.today()
    maxi = _jour(maxi) or date.today() + timedelta(days=FENETRE_API_JOURS)
    choisi = _jour(retour)
    if choisi and not (mini <= choisi <= maxi):
        choisi = None
    return (choisi.isoformat() if choisi else None), mini.isoformat(), maxi.isoformat()


@app.callback(
    [Output("time-picker-retour", "options"), Output("time-picker-retour", "value")],
    [Input("date-picker-retour", "date"), Input("date-picker-aller", "date"), Input("time-picker-aller", "value")],
    State("time-picker-retour", "value")
)
def heures_retour(retour, jour, heure, heure_retour):
    """Le retour part au moins une heure après l'aller : les heures qui précèdent sont grisées."""
    aller = _quand_aller(_jour(jour), heure)
    options = options_heures(_jour(retour), retour_minimum(aller))
    return options, (None if any(o["disabled"] and o["value"] == heure_retour for o in options) else heure_retour)


# Caractères des icônes Font Awesome (city, landmark, camera, masks-theater, location-dot), affichés par src/assets/menus.css
PICTOS_DESTINATION = {"ville": "\uf64f", "culture": "\uf66f", "tourisme": "\uf030", "evenement": "\uf630"}
PICTO_LIEU = "\uf3c5"


def _option_destination(o, recherche=""):
    """Option du menu de destination, précédée de l'icône de son type : ville, événement, culture ou tourisme.
    Libellé en texte seul : un composant (icône) dans le libellé fait planter le rendu de Dash quand les options changent pendant la saisie
    (« Cannot read properties of undefined (reading 'props') », puis la page se recharge).
    Le menu (Dash 4) refiltre les options dans le navigateur sur le texte « search » : il cacherait la ville de Huez pour « Alpe d'Huez ».
    Toutes les options reçoivent donc la saisie comme texte de recherche (le tri, lui, est gardé par search_order="original")."""
    return {"label": f"{PICTOS_DESTINATION.get(o['type'], PICTO_LIEU)}  {o['label']}", "value": o["value"], "search": recherche or o["label"]}


@app.callback(
    Output("input-arrivee", "options"),
    [Input("input-arrivee", "search_value"), Input("filter-categorie", "value")],
    State("input-arrivee", "value")
)
def update_destinations(recherche, categorie, choisi):
    try:
        return [_option_destination(o, recherche) for o in chercher_destinations(recherche, categorie, engine, inclure=choisi)]
    except Exception:
        return []

@app.callback(
    [Output("main-container", "style"), Output("main-container", "className"), Output("top-bar", "style"), Output("search-panel", "style"), Output("logo-img", "style"),
     Output("tab2-search-bar", "style"),
     Output("card-kpi-dist", "style"), Output("card-kpi-trans", "style"), Output("card-kpi-statut", "style"),
     Output("card-kpi-global-1", "style"), Output("card-kpi-global-2", "style"), Output("card-kpi-global-3", "style"),
     Output("card-map", "style"), Output("card-g1", "style"), Output("card-g3", "style"),
     Output("card-g4-saison", "style"), Output("card-outils", "style"),
     Output("map-tiles", "url"), Output("card-map", "className"),
     Output("t2-kpi-couverture", "children"), Output("t2-kpi-sites", "children"), Output("t2-kpi-blanches", "children"),
     Output("graph-1", "figure"), Output("graph-3", "figure"), Output("graph-4", "figure"),
     Output("table-container", "children"),
     Output("drilldown-text", "children"), Output("btn-reset-drilldown", "style"),
     Output("card-results", "style")],
    [Input("theme-switch", "value"), Input("filter-categorie", "value"), 
     Input("btn-search-t2", "n_clicks"), Input("t2-table-mode", "value"),
     Input("graph-1", "clickData"), Input("btn-reset-drilldown", "n_clicks")],
    [State("t2-region", "value"), State("t2-depart", "value"), State("t2-arrivee", "value"), State("t2-train", "value")]
)
def update_ui_and_graphs(theme_values, categorie, t2_clicks, table_mode, click_data, reset_clicks, t2_regions, t2_depart, t2_arrivee, t2_train):
    theme = "dark" if theme_values and "dark" in theme_values else "light"
    colors = THEME_COLORS[theme]
    
    card_st = {"backgroundColor": colors["card_bg"], "color": colors["text"], **transition_style}
    
    card_iti = {**card_st, "border": "none"}         # cartes de l'onglet Itinéraire
    
    search_panel_st = {
        "position": "absolute", "top": "20px", "left": "20px", "zIndex": "1000",
        "backgroundColor": colors["card_bg"], "color": colors["text"],
        "padding": "20px", "borderRadius": "15px", "boxShadow": "0px 4px 15px rgba(0,0,0,0.2)",
        "width": "340px", **transition_style
    }
    
    search_bar_t2_st = {"backgroundColor": colors["card_bg"], "color": colors["text"], **transition_style}
    
    logo_bg = "rgba(255, 255, 255, 0.9)" if theme == "dark" else "transparent"
    logo_st = {"maxHeight": "42px", "objectFit": "contain", "borderRadius": "6px", "padding": "2px", "backgroundColor": logo_bg, **transition_style}
    
    layout_shared = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color=colors["text"]), margin=dict(l=25, r=25, t=35, b=25))
    
    # Gestion du Drill-down / Brushing & Linking via clic sur Graphe 1
    selected_regions = t2_regions
    triggered_id = ctx.triggered_id
    
    if triggered_id == "btn-reset-drilldown":
        selected_regions = None
    elif triggered_id == "graph-1" and click_data and "points" in click_data:
        clicked_custom = click_data["points"][0].get("customdata", [None])[0]
        if clicked_custom:
            code_dept = str(clicked_custom).split(" - ")[0].strip()
            selected_regions = [code_dept]

    # Status du filtre actif (Signifiant visuel Roll-up)
    if selected_regions:
        label_reg = ", ".join([DEPARTEMENTS_MAP.get(str(r).zfill(2), str(r)) for r in (selected_regions if isinstance(selected_regions, list) else [selected_regions])])
        drilldown_text = f"🎯 Filtre actif : {label_reg}"
        btn_reset_style = {"display": "inline-block", "fontSize": "0.75rem", "padding": "2px 8px"}
    else:
        drilldown_text = "💡 Cliquez sur un point du Graphe 1 pour zoomer (Drill-down)"
        btn_reset_style = {"display": "none", "fontSize": "0.75rem", "padding": "2px 8px"}

    df_iaf, df_distance, df_saison, kpi_couv, kpi_sites, kpi_blanc = get_tab2_data(categorie, selected_regions, t2_depart, t2_arrivee, t2_train)
    
    # --------------------------------------------------------------------------
    # GRAPHE 1 : Scatter Plot (Pleine Hauteur Gauche)
    # --------------------------------------------------------------------------
    extrema_codes = ["75", "92", "93", "78", "07", "32", "04", "23"]
    df_iaf['Label_Visible'] = df_iaf.apply(
        lambda r: r['Departement_Nom'] if any(c in str(r['Departement_Code']) for c in extrema_codes) else "", axis=1
    )

    fig1 = px.scatter(
        df_iaf, x="Nombre_POI", y="IAF", text="Label_Visible", color="IAF",
        custom_data=["Departement_Nom"],
        color_continuous_scale=["#b91c1c", "#f59e0b", "#10b981"],
        log_x=True,
        title="<b>Volume de sites × accessibilité ferroviaire par département</b>",
        labels={"Nombre_POI": "nombre de sites (log)", "IAF": "IAF"}
    )
    fig1.update_traces(
        marker=dict(size=12, opacity=0.85, line=dict(width=1, color="DarkSlateGrey")),
        textposition='top center',
        hovertemplate="<b>%{customdata[0]}</b><br>Sites : %{x}<br>Indice IAF : %{y}<extra></extra>"
    )
    fig1.add_hline(y=38, line_dash="dash", line_color="#4b5563", annotation_text="France : 38", annotation_position="bottom right")
    fig1.update_layout(
        **layout_shared, showlegend=False, coloraxis_showscale=False,
        clickmode='event+select'
    )

    # --------------------------------------------------------------------------
    # GRAPHE 3 : Répartition par Tranche de Distance (Haut Droite)
    # --------------------------------------------------------------------------
    fig3 = px.bar(
        df_distance, x="Tranche", y="Nombre", color="Categorie",
        color_discrete_sequence=COLORBLIND_PALETTE,
        title="<b>Répartition des sites par tranche de distance</b>",
        labels={"Tranche": "Transport recommandé", "Nombre": "Sites"},
        category_orders={"Tranche": ["≤ 1,5 km (Pied)", "1,5-5 km (Vélo/Bus)", "5-15 km (Navette)", "> 15 km (Voiture)"]}
    )
    fig3.update_traces(hovertemplate="Catégorie : %{fullData.name}<br>Nombre : %{y}<extra></extra>")
    fig3.update_layout(**layout_shared, barmode="stack", yaxis_rangemode="tozero")

    # --------------------------------------------------------------------------
    # GRAPHE 4 : Saisonnalité Événementielle (Bas Droite)
    # --------------------------------------------------------------------------
    fig4 = px.area(
        df_saison, x="Mois", y="Evenements", markers=True,
        color_discrete_sequence=[COLORBLIND_PALETTE[1]],
        title="<b>Saisonnalité de la demande événementielle par mois</b>",
        labels={"Mois": "Mois", "Evenements": "Événements"}
    )
    fig4.update_traces(hovertemplate="Mois : %{x}<br>Événements : %{y}<extra></extra>")
    fig4.update_layout(**layout_shared, yaxis_rangemode="tozero")

    return (
        {"backgroundColor": colors["bg"], "color": colors["text"], "minHeight": "100vh", "padding": "12px 20px", **transition_style},
        colors["root_class"],
        {"backgroundColor": colors["card_bg"], "borderRadius": "12px", "color": colors["text"], **transition_style}, 
        search_panel_st, logo_st, search_bar_t2_st,
        card_iti, card_iti, card_iti,
        card_st, card_st, card_st,
        {"backgroundColor": colors["card_bg"], "color": colors["text"], "border": "none", "height": HAUTEUR_CARTE, "position": "relative", "overflow": "hidden", **transition_style},
        card_st, card_st, card_st, card_st,
        colors["tiles"], colors["map_class"],
        kpi_couv, kpi_sites, kpi_blanc,
        fig1, fig3, fig4, generate_decision_table(theme, selected_regions, mode=table_mode),
        drilldown_text, btn_reset_style, card_iti
    )

POI_COULEURS = {"culture": COLORBLIND_PALETTE[0], "tourisme": "#984ea3", "evenement": COLORBLIND_PALETTE[1]}
POI_LIBELLES = {"culture": "Musée / culture", "tourisme": "Tourisme", "evenement": "Festival / événement"}
POI_ICONES = {"culture": "fa-landmark", "tourisme": "fa-camera", "evenement": "fa-masks-theater"}
POI_PAR_CATEGORIE = {"tous": ["tourisme", "culture", "evenement"], "culture": ["culture"], "tourisme": ["tourisme"], "evenement": ["evenement"]}


def _duree(secondes):
    h, m = divmod(round(secondes / 60), 60)
    return f"{h} h {m:02d}" if h else f"{m} min"

def _heure(texte):
    return datetime.fromisoformat(texte).strftime("%H:%M")

def _echantillon(couleur, tirets):
    """Petit trait qui reprend la couleur et le motif d'un service (pour reconnaître la ligne sur la carte sans se fier à la couleur)."""
    base = {"display": "inline-block", "width": "38px", "height": "5px", "marginRight": "8px", "verticalAlign": "middle", "borderRadius": "3px"}
    if not tirets:
        return html.Span(style={**base, "backgroundColor": couleur})
    arrets, position = [], 0.0
    for i, v in enumerate(float(v) * 1.6 for v in tirets.split()):         # rangs pairs : trait, rangs impairs : vide
        arrets.append(f"{couleur if i % 2 == 0 else 'transparent'} {position:.0f}px {position + v:.0f}px")
        position += v
    return html.Span(style={**base, "background": f"repeating-linear-gradient(90deg, {', '.join(arrets)})"})

def _carte_option(i, trajet, actif, traces, etiquettes=()):
    """Un bloc cliquable : étiquettes (le plus rapide…), heures, durée, correspondances, puis un trait + le nom de chaque train."""
    puces = [html.Span([html.I(className=f"fa-solid {icone} me-1"), texte], className="badge rounded-pill me-1", style={"backgroundColor": couleur, "fontSize": "0.68rem"})
             for texte, icone, couleur in etiquettes]
    lignes = [html.Div(className="mb-0", style={"fontSize": "0.8rem", "whiteSpace": "nowrap", "overflow": "hidden", "textOverflow": "ellipsis"}, children=[_echantillon(t["style"]["couleur"], t["style"]["tirets"]), html.Span(t["libelle"], className="fw-bold" if not t["marche"] else ""),
                                                   html.Span("" if t["marche"] else f" · {t['style']['libelle']}", style={"opacity": 0.7})]) for t in traces]
    co2 = trajet.get("co2_g")
    retard = max([sec.get("retard_min") or 0 for sec in trajet["sections"] if sec["type"] == "public_transport"] or [0])
    return html.Div(style={"flex": "0 0 auto"}, children=html.Div(id={"type": "option", "index": i}, n_clicks=0, role="button", tabIndex=0, children=[
        *([html.Div(puces, className="mb-2")] if puces else []),
        html.Div([html.Span(f"Option {i + 1}", className="badge me-2", style={"backgroundColor": CARMILLON if actif else "#6c757d"}),
                  html.Span(f"{_heure(trajet['depart'])} → {_heure(trajet['arrivee'])}", className="fs-6 fw-bold")]),
        html.Div(f"{_duree(trajet['duree_s'])} · " + (f"{trajet['correspondances']} corresp." if trajet["correspondances"] else "direct")
                 + (f" · {co2 / 1000:.1f} kg CO₂e" if co2 else ""), className="mb-1", style={"opacity": 0.8, "fontSize": "0.78rem"}),
        *([html.Div(f"Retard annoncé : {retard} min", className="mb-2 fw-bold", style={"color": "#c0392b"})] if retard else []),
        *(lignes if actif else []),                   # le détail des trains n'apparaît qu'au clic sur l'option
    ], style={"cursor": "pointer", "padding": "8px 10px", "borderRadius": "10px", "height": "100%",
              "border": f"3px solid {CARMILLON}" if actif else "1px solid rgba(128,128,128,0.35)",
              "boxShadow": "0px 4px 14px rgba(0,0,0,0.18)" if actif else "none", "transition": "all 0.2s ease"}))

def _pastille(type_, taille=26):
    """Style d'une pastille ronde de la couleur de la catégorie, avec le pictogramme en blanc (comme les repères de Google Maps)."""
    return {"width": f"{taille}px", "height": f"{taille}px", "borderRadius": "50%", "background": POI_COULEURS.get(type_, "#555555"), "color": "white",
            "border": "2px solid white", "boxShadow": "0 1px 5px rgba(0,0,0,0.45)", "display": "flex", "alignItems": "center", "justifyContent": "center",
            "fontSize": f"{taille // 2}px"}

def _css(style):
    """Style Dash (camelCase) → texte CSS, pour le HTML des repères de la carte."""
    return "; ".join(f"{re.sub('([A-Z])', lambda m: '-' + m.group(1).lower(), cle)}: {valeur}" for cle, valeur in style.items())

def _trait(points, style, epaisseur):
    """Un trait de la carte : liseré blanc dessous (sauf pour les points, où il formerait un trait plein), puis la couleur et le motif du service."""
    pointille = style["cle"] in ("bus", "pied")
    trait = dl.Polyline(positions=points, color=style["couleur"], weight=epaisseur + 1 if pointille else epaisseur, dashArray=style["tirets"],
                        lineCap="round" if style["cle"] in ("rer", "bus", "pied") else "butt")
    return [trait] if pointille else [dl.Polyline(positions=points, color="white", weight=epaisseur + 4, opacity=0.9), trait]

def _calques(r, traces, categorie):
    """(lignes, cercle, repères) de la carte : un trait par train (liseré blanc dessous), dernier kilomètre en pointillés, lieux de la catégorie autour de la destination."""
    dep, dest, gare = r["depart"], r["destination"], r["gare_arrivee"]
    lignes = []
    for t in traces:
        if not t["marche"]:                                  # la marche est dessinée en empreintes de pas par trains.js (store-pas)
            lignes += _trait(t["points"], t["style"], 5)
    reperes = [dl.Marker(position=[dep["lat"], dep["lon"]], children=[dl.Tooltip(f"Départ : {dep['nom']}")]),
               dl.Marker(position=[dest["lat"], dest["lon"]], children=[dl.Tooltip(f"Destination : {dest['nom']}")])]
    if gare and r["dernier_km"][0] != "Marche à pied":       # à pied : empreintes ; en vélo, bus ou voiture : trait, expliqué dans la légende
        lignes += _trait([[gare["lat"], gare["lon"]], [dest["lat"], dest["lon"]]], style_dernier_km(r["dernier_km"][0]), 4)
        reperes.append(dl.CircleMarker(center=[gare["lat"], gare["lon"]], radius=8, color=CARMILLON, fillOpacity=0.9, children=[dl.Tooltip(f"Gare d'arrivée : {gare['nom']}")]))
    reperes += [dl.DivMarker(position=[p["lat"], p["lon"]], iconOptions=dict(className="poi-pastille", iconSize=[26, 26], iconAnchor=[13, 13],
                                                                             html=f'<div style="{_css(_pastille(p["type"]))}"><i class="fa-solid {POI_ICONES.get(p["type"], "fa-location-dot")}"></i></div>'),
                             children=[dl.Tooltip(f"{p['nom'] or p['type']} · {POI_LIBELLES.get(p['type'], p['type'])} · {p['distance_km']:.1f} km de la destination")])
                for p in r["pois"] if p["type"] in POI_PAR_CATEGORIE.get(categorie, POI_PAR_CATEGORIE["tous"])]
    cercle = [dl.Circle(center=[dest["lat"], dest["lon"]], radius=RAYON_POI_KM * 1000, color="#555555", weight=2, fillOpacity=0.05)]
    return lignes, cercle, reperes

def _message(texte, niveau="muted"):
    return html.Div(texte, className=f"text-{niveau}")


@app.callback(
    [Output("kpi-distance", "children"), Output("kpi-intermodal", "children"), Output("kpi-statut", "children"),
     Output("kpi-distance-detail", "children"), Output("kpi-intermodal-detail", "children"),
     Output("store-resultat", "data"), Output("store-selection", "data"), Output("sens", "value"), Output("store-horloge", "data")],
    Input("btn-search", "n_clicks"),
    [State("input-depart", "value"), State("input-arrivee", "value"),
     State("date-picker-aller", "date"), State("time-picker-aller", "value"),
     State("switch-ar", "value"), State("date-picker-retour", "date"), State("time-picker-retour", "value")],
    running=[(Output("btn-search", "disabled"), True, False)],
    prevent_initial_call=True
)
def lancer_recherche(n_clicks, depart, arrivee, date_aller, heure_aller, aller_retour, date_retour, heure_retour):
    """Interroge la base et l'API SNCF, puis range le résultat dans store-resultat : l'affichage (trajets, carte) s'en sert sans rappeler l'API."""
    vide = ("-- km", "--", "--", "", "")
    reset = ({"sens": "aller", "index": 0}, "aller", {"mode": "reel"})
    if not depart or not arrivee:
        return (*vide, {"message": "Choisissez une gare de départ et une destination.", "niveau": "muted"}, *reset)
    try:
        quand = quand_depuis(date_aller, heure_aller) if date_aller else None
        retour = quand_depuis(date_retour, heure_retour) if aller_retour and 1 in aller_retour and date_retour else None
        r = rechercher(depart, arrivee, quand=quand, retour=retour, engine=engine)
    except Exception as erreur:
        return (*vide, {"message": f"Recherche impossible : {type(erreur).__name__}", "niveau": "danger"}, *reset)
    if r is None:
        return (*vide, {"message": "Lieu introuvable en base.", "niveau": "danger"}, *reset)

    mode, detail_mode = r["dernier_km"]
    km, gare = r["distance_km"], r["gare_arrivee"]
    statut = "--" if r["faisable"] is None else "Faisable" if r["faisable"] else "Difficile"
    r["pois"] = r["pois"].to_dict("records")
    donnees = json.loads(json.dumps(r, default=str))          # datetimes → texte : le résultat voyage dans un dcc.Store
    return (f"{km:.1f} km" if km is not None else "-- km", mode, statut, f"depuis {gare['nom']}" if gare else "", detail_mode, donnees, *reset)


@app.callback(
    [Output("store-selection", "data", allow_duplicate=True), Output("store-horloge", "data", allow_duplicate=True)],
    [Input({"type": "option", "index": ALL}, "n_clicks"), Input("sens", "value")],
    State("store-selection", "data"),
    prevent_initial_call=True
)
def choisir_option(clics, sens, selection):
    """Un clic sur un bloc choisit cette option ; Aller / Retour repart sur la première option."""
    declencheur = ctx.triggered_id
    if declencheur == "sens":
        if sens == selection["sens"]:
            raise PreventUpdate
        return {"sens": sens, "index": 0}, {"mode": "reel"}
    if isinstance(declencheur, dict) and ctx.triggered[0]["value"]:        # n_clicks vide = bloc qui vient d'apparaître, pas un clic
        return {"sens": selection["sens"], "index": declencheur["index"]}, {"mode": "reel"}
    raise PreventUpdate


@app.callback(
    [Output("options-trajets", "children"), Output("results-title", "children"), Output("poi-legend", "children"), Output("col-sens", "style"),
     Output("kpi-statut-detail", "children"),
     Output("map-lines", "children"), Output("map-isochrones", "children"), Output("map-markers", "children"), Output("map", "viewport"),
     Output("store-etapes", "data"), Output("store-pas", "data")],
    [Input("store-resultat", "data"), Input("store-selection", "data"), Input("filter-categorie", "value")]
)
def afficher_resultat(r, selection, categorie):
    """Blocs des options et carte, d'après le résultat de la recherche et l'option choisie."""
    if not r:
        raise PreventUpdate
    nouveau = "store-resultat.data" in ctx.triggered_prop_ids
    cache, visible = {"display": "none"}, {"display": "block"}
    if "message" in r:
        return _message(r["message"], r["niveau"]), "Trajets proposés", [], cache, "", [], [], [], dash.no_update, None, []

    dep, gare = r["depart"], r["gare_arrivee"]
    retour = selection["sens"] == "retour" and bool(r["trajets_retour"])
    trajets = r["trajets_retour"] if retour else r["trajets"]
    index = min(selection["index"], max(len(trajets) - 1, 0))
    de, vers = (gare, dep) if retour else (dep, gare)
    titre = f"{'Retour' if retour else 'Aller'} · {de['nom']} → {vers['nom']}" if gare else "Trajets proposés"
    liaison = ((de["lon"], de["lat"]), (vers["lon"], vers["lat"])) if gare else ((dep["lon"], dep["lat"]),) * 2

    traces_options = [tracer_trajet(t, reseau_ferre, *liaison) for t in trajets]
    traces = traces_options[index] if trajets else tracer_trajet(None, reseau_ferre, *liaison)
    if r["erreur_api"]:
        blocs = _message(f"Horaires indisponibles ({r['erreur_api']}). La liaison directe entre les gares est tracée.", "warning")
    elif gare is None:
        blocs = _message("Aucune gare d'arrivée connue pour ce lieu.", "warning")
    elif r["meme_gare"]:
        blocs = _message(f"La gare la plus proche de cette destination est la gare de départ ({gare['nom']}) : aucun train à prendre.", "info")
    elif r["periode_invalide"]:
        blocs = _message(r["periode_invalide"], "warning")
    elif not trajets:
        blocs = _message("Aucun train trouvé pour ce créneau.", "warning")
    else:
        etiquettes = etiquettes_trajets(trajets)
        blocs = html.Div([_carte_option(i, t, i == index, traces_options[i], etiquettes[i]) for i, t in enumerate(trajets)],
                         style={"display": "flex", "flexDirection": "column", "gap": "8px"})

    co2 = trajets[index].get("co2_g") if trajets else None
    detail_statut = f"Train : {co2 / 1000:.1f} kg CO₂e par voyageur" if co2 else ("Horaires indisponibles" if r["erreur_api"] else "")
    lignes, cercle, reperes = _calques(r, traces, categorie)
    viewport = dash.no_update
    if nouveau:
        points = [p for t in traces for p in t["points"]] + [[r["destination"]["lat"], r["destination"]["lon"]]]
        viewport = dict(bounds=[[min(p[0] for p in points), min(p[1] for p in points)], [max(p[0] for p in points), max(p[1] for p in points)]], transition="flyTo")
    for t in traces:                                    # ce dont le navigateur a besoin pour dessiner le train (image, taille réelle)
        t.update(sprites.infos(t["style"]["cle"], t["libelle"]))
    pas = [t["points"] for t in traces if t["marche"]]  # trajets à pied, dessinés en empreintes de pas
    if gare and r["dernier_km"][0] == "Marche à pied":
        pas.append([[gare["lat"], gare["lon"]], [r["destination"]["lat"], r["destination"]["lon"]]])
    return (blocs, titre, [], visible if r["trajets_retour"] else cache, detail_statut,
            lignes, cercle, reperes, viewport, traces, pas)

@app.callback(
    Output("store-horloge", "data", allow_duplicate=True),
    Input("btn-sim", "n_clicks"),
    State("store-horloge", "data"),
    prevent_initial_call=True
)
def basculer_simulation(clics, horloge):
    """Par défaut le suivi est en temps réel. « Simuler le trajet » le fait défiler depuis son départ à vitesse accélérée ; le même bouton arrête la simulation."""
    if horloge and horloge.get("mode") == "sim":
        return {"mode": "reel"}
    return {"mode": "sim", "t0_reel": time.time()}


@app.callback(
    [Output("panneau-resultats", "style"), Output("btn-ouvrir", "style")],
    [Input("btn-fermer", "n_clicks"), Input("btn-ouvrir", "n_clicks"), Input("store-resultat", "data")],
    prevent_initial_call=True
)
def ouvrir_ou_fermer_les_trajets(fermer, ouvrir, resultat):
    """Le panneau des trajets s'ouvre à chaque recherche ; la croix le masque et « Afficher les trajets » le rouvre."""
    if ctx.triggered_id == "store-resultat" and not resultat:
        raise PreventUpdate
    ouvert = ctx.triggered_id != "btn-fermer"
    return {**STYLE_PANNEAU, "display": "block" if ouvert else "none"}, {**STYLE_OUVRIR, "display": "none" if ouvert else "block"}


@app.callback(
    [Output("suivi-etat", "children"), Output("btn-sim", "active"), Output("btn-sim", "children")],
    [Input("tick", "n_intervals"), Input("store-etapes", "data"), Input("store-horloge", "data")]
)
def etat_du_suivi(_, etapes, horloge):
    """Texte d'état (où en est le train) chaque seconde ; les trains eux-mêmes sont animés dans le navigateur (src/assets/trains.js)."""
    simulation = bool(horloge) and horloge.get("mode") == "sim"
    bouton = [html.I(className="fa-solid fa-stop me-2"), "Arrêter la simulation"] if simulation else [html.I(className="fa-solid fa-play me-2"), "Simuler le trajet"]
    if not etapes:
        return "", simulation, bouton
    maintenant = datetime.now()
    if simulation:
        departs = [datetime.fromisoformat(e["depart"]) for e in etapes if e.get("depart") and not e["marche"]]
        if departs:
            maintenant = suivi.horloge_simulee(min(departs), datetime.fromtimestamp(horloge["t0_reel"]), maintenant)
    etat = suivi.suivre(etapes, maintenant)
    entete = f"Simulation · {maintenant:%d/%m %H:%M} — " if simulation else f"Temps réel · {maintenant:%H:%M} — "
    return entete + etat["message"], simulation, bouton


@app.callback(
    [Output("store-tous", "data"), Output("btn-tous", "active"), Output("btn-tous-texte", "children")],
    [Input("btn-tous", "n_clicks"), Input("tick-tous", "n_intervals")],
    State("store-tous", "data"),
    running=[(Output("btn-tous", "disabled"), True, False)],
    prevent_initial_call=True
)
def trains_du_reseau(clics, _, actuel):
    """Bouton du bandeau : affiche (ou cache) tous les trains qui roulent sur le réseau, d'après les horaires théoriques. Rafraîchi toutes les 2 minutes."""
    actif = bool(actuel and actuel.get("actif"))
    if ctx.triggered_id == "btn-tous":
        actif = not actif
    elif not actif:
        raise PreventUpdate                       # le rafraîchissement ne fait rien tant que le bouton est éteint
    if not actif:
        return {"actif": False, "trains": []}, False, "Tous les trains en direct"
    try:
        trains = circulations.en_cours(datetime.now(), engine)
    except Exception:
        return {"actif": False, "trains": []}, False, "Tous les trains en direct (indisponible)"
    return {"actif": True, "trains": trains}, True, f"{len(trains)} trains en circulation"


# Animation des trains dans le navigateur (src/assets/trains.js) : fluide, à l'échelle de la carte, clic pour suivre un train.
app.clientside_callback(
    ClientsideFunction(namespace="trains", function_name="configurer"),
    Output("store-js", "data"),
    [Input("store-etapes", "data"), Input("store-horloge", "data")]
)


app.clientside_callback(
    ClientsideFunction(namespace="trains", function_name="recentrer"),
    Output("store-js-centre", "data"),
    Input("btn-centrer", "n_clicks"),
    prevent_initial_call=True
)

app.clientside_callback(
    ClientsideFunction(namespace="trains", function_name="configurerPas"),
    Output("store-js-pas", "data"),
    Input("store-pas", "data")
)

app.clientside_callback(
    ClientsideFunction(namespace="trains", function_name="configurerTous"),
    Output("store-js-tous", "data"),
    Input("store-tous", "data")
)


@app.server.route("/sprite-train/<cle>.png")
def sprite_train(cle):
    """Image d'un train, recadrée en mémoire à partir de assets/train/ (voir lib/sprites.py)."""
    png = sprites.sprite_png(cle) if cle in sprites.IMAGES else None
    if png is None:
        abort(404)
    return Response(png, mimetype="image/png", headers={"Cache-Control": "public, max-age=86400"})


if __name__ == "__main__":
    app.run(debug=True)