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
from dash import dcc, html, Input, Output, State, ctx
import dash_bootstrap_components as dbc
import dash_leaflet as dl
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np

from lib.db.connection import get_engine

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
    },
    "dark": {
        "bg": "#11151c", 
        "card_bg": "#1a202c", 
        "text": "#f1f1f1",
        "tiles": "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    }
}
transition_style = {"transition": "background-color 0.4s ease, color 0.4s ease"}
engine = get_engine()

def get_gares_options():
    try:
        df_gares = pd.read_sql("SELECT DISTINCT nom FROM lieu WHERE type = 'gare' AND nom IS NOT NULL ORDER BY nom", engine)
        return [{'label': g, 'value': g} for g in df_gares['nom'].tolist()]
    except Exception:
        return [{'label': "Paris Gare de Lyon", 'value': "Paris Gare de Lyon"}]

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
init_colors = THEME_COLORS["light"]
gares_opts = get_gares_options()
destinations_opts = get_destinations_options()
departements_opts = get_departements_options()
hours_opts = [{'label': f"{h:02d}:00", 'value': f"{h:02d}:00"} for h in range(5, 24)]

app.layout = dbc.Container(id="main-container", style={"backgroundColor": init_colors["bg"], "color": init_colors["text"], "minHeight": "100vh", "padding": "12px 20px", **transition_style}, fluid=True, children=[
    dcc.Download(id="download-export"),
    dcc.Store(id="store-selected-dept", data=None),
    
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
            dbc.Col(dbc.Card(id="card-kpi-dist", className="kpi-card", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "borderTopColor": COLORBLIND_PALETTE[3], **transition_style}, children=[dbc.CardBody([
                html.H6("Distance Gare -> Destination", className="text-uppercase text-muted fw-bold", style={"fontSize": "0.75rem"}), html.H3(id="kpi-distance", children="-- km", style={"color": COLORBLIND_PALETTE[3], "fontWeight": "bold"})
            ])]), width=4),
            dbc.Col(dbc.Card(id="card-kpi-trans", className="kpi-card", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "borderTopColor": COLORBLIND_PALETTE[1], **transition_style}, children=[dbc.CardBody([
                html.H6("Transport 1er/Dernier km", className="text-uppercase text-muted fw-bold", style={"fontSize": "0.75rem"}), html.H3(id="kpi-intermodal", children="--", style={"color": COLORBLIND_PALETTE[1], "fontWeight": "bold"})
            ])]), width=4),
            dbc.Col(dbc.Card(id="card-kpi-statut", className="kpi-card", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "borderTopColor": COLORBLIND_PALETTE[0], **transition_style}, children=[dbc.CardBody([
                html.H6("Faisabilité Décarbonée", className="text-uppercase text-muted fw-bold", style={"fontSize": "0.75rem"}), html.H3(id="kpi-statut", children="--", style={"color": COLORBLIND_PALETTE[0], "fontWeight": "bold"})
            ])]), width=4),
        ], className="g-3 mb-3"),

        dbc.Row([
            dbc.Col([
                dbc.Card(id="card-map", className="dash-card", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "height": "580px", "position": "relative", **transition_style}, children=[
                    dcc.Loading(custom_spinner=custom_spinner, children=[
                        html.Div(style={"position": "relative"}, children=[
                            
                            # PANNEAU RECHERCHE FLOTTANT
                            html.Div(id="search-panel", style={
                                "position": "absolute", "top": "15px", "left": "15px", "zIndex": "1000",
                                "backgroundColor": init_colors["card_bg"], "color": init_colors["text"],
                                "padding": "15px", "borderRadius": "12px", "boxShadow": "0px 4px 15px rgba(0,0,0,0.2)",
                                "width": "320px", **transition_style
                            }, children=[
                                html.H5(html.I(className="fa-solid fa-route me-2"), className="mb-2", style={"color": CARMILLON}),
                                
                                html.Label("Départ :", htmlFor="input-depart", className="fw-bold mb-1", style={"fontSize": "0.85rem"}),
                                dcc.Dropdown(id="input-depart", options=gares_opts, placeholder="Départ...", searchable=True, className="mb-2"),
                                
                                html.Label("Destination :", htmlFor="input-arrivee", className="fw-bold mb-1", style={"fontSize": "0.85rem"}),
                                dcc.Dropdown(id="input-arrivee", options=destinations_opts, placeholder="Destination...", searchable=True, className="mb-2"),
                                
                                html.Label("Aller :", htmlFor="date-picker-aller", className="fw-bold mb-1", style={"fontSize": "0.85rem"}),
                                dbc.Row(className="g-2 mb-2", children=[
                                    dbc.Col(dcc.DatePickerSingle(id="date-picker-aller", date=date.today(), display_format="DD/MM/YYYY"), width=7),
                                    dbc.Col(dcc.Dropdown(id="time-picker-aller", options=hours_opts, placeholder="Heure"), width=5),
                                ]),
                                
                                dbc.Checklist(options=[{"label": "Trajet Aller/Retour", "value": 1}], value=[], id="switch-ar", switch=True, className="fw-bold mb-2", style={"fontSize": "0.85rem"}),
                                
                                html.Div(id="row-retour", style={"display": "none"}, children=[
                                    html.Label("Retour :", htmlFor="date-picker-retour", className="fw-bold mb-1", style={"fontSize": "0.85rem"}),
                                    dbc.Row(className="g-2 mb-2", children=[
                                        dbc.Col(dcc.DatePickerSingle(id="date-picker-retour", display_format="DD/MM/YYYY", placeholder="Date retour"), width=7),
                                        dbc.Col(dcc.Dropdown(id="time-picker-retour", options=hours_opts, placeholder="Heure"), width=5),
                                    ])
                                ]),
                                
                                html.Hr(className="my-2", style={"opacity": "0.1"}),
                                
                                html.Label("Catégorie de POI :", htmlFor="filter-categorie", className="fw-bold mb-1", style={"fontSize": "0.85rem"}),
                                dbc.RadioItems(
                                    id="filter-categorie",
                                    options=[
                                        {"label": html.Span([html.I(className="fa-solid fa-map-location-dot me-1"), "Toutes"]), "value": "tous"},
                                        {"label": html.Span([html.I(className="fa-solid fa-landmark me-1"), "Culture"]), "value": "culture"},
                                        {"label": html.Span([html.I(className="fa-solid fa-masks-theater me-1"), "Festivals"]), "value": "evenement"}
                                    ],
                                    value="tous", className="fw-bold mb-3", style={"fontSize": "0.8rem"}
                                ),
                                
                                dbc.Button([html.I(className="fa-solid fa-magnifying-glass me-2"), "Rechercher"], id="btn-search", style={"backgroundColor": CARMILLON, "border": "none", "width": "100%", "fontWeight": "bold", "padding": "8px"})
                            ]),

                            dl.Map(id="map", center=[46.2, 3.5], zoom=5, style={"width": "100%", "height": "580px", "display": "block", "margin": "0"}, children=[
                                dl.TileLayer(id="map-tiles", url=init_colors["tiles"]),
                                dl.LayerGroup(id="map-lines"), dl.LayerGroup(id="map-isochrones"), dl.LayerGroup(id="map-markers")
                            ])
                        ])
                    ])
                ])
            ], width=12)
        ])
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
                        dbc.Card(className="dash-card p-2 px-3", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], **transition_style}, children=[
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

@app.callback(
    Output("input-arrivee", "options"),
    [Input("filter-categorie", "value")]
)
def update_poi_dropdown(categorie):
    try:
        type_filter = "IN ('culture', 'tourisme')" if categorie == "culture" else "IN ('evenement')" if categorie == "evenement" else "NOT IN ('gare', 'arret_bus', 'arret_train')"
        return [{'label': p, 'value': p} for p in pd.read_sql(f"SELECT DISTINCT nom FROM lieu WHERE type {type_filter} AND nom IS NOT NULL ORDER BY nom LIMIT 1000", engine)['nom'].tolist()]
    except Exception: 
        return [{'label': p, 'value': p} for p in ["Château de Versailles", "Musée du Louvre"]]

@app.callback(
    [Output("main-container", "style"), Output("top-bar", "style"), Output("search-panel", "style"), Output("logo-img", "style"),
     Output("tab2-search-bar", "style"),
     Output("card-kpi-dist", "style"), Output("card-kpi-trans", "style"), Output("card-kpi-statut", "style"),
     Output("card-kpi-global-1", "style"), Output("card-kpi-global-2", "style"), Output("card-kpi-global-3", "style"),
     Output("card-map", "style"), Output("card-g1", "style"), Output("card-g3", "style"),
     Output("card-g4-saison", "style"),
     Output("map-tiles", "url"),
     Output("t2-kpi-couverture", "children"), Output("t2-kpi-sites", "children"), Output("t2-kpi-blanches", "children"),
     Output("graph-1", "figure"), Output("graph-3", "figure"), Output("graph-4", "figure"),
     Output("table-container", "children"),
     Output("drilldown-text", "children"), Output("btn-reset-drilldown", "style")],
    [Input("theme-switch", "value"), Input("filter-categorie", "value"), 
     Input("btn-search-t2", "n_clicks"), Input("t2-table-mode", "value"),
     Input("graph-1", "clickData"), Input("btn-reset-drilldown", "n_clicks")],
    [State("t2-region", "value"), State("t2-depart", "value"), State("t2-arrivee", "value"), State("t2-train", "value")]
)
def update_ui_and_graphs(theme_values, categorie, t2_clicks, table_mode, click_data, reset_clicks, t2_regions, t2_depart, t2_arrivee, t2_train):
    theme = "dark" if theme_values and "dark" in theme_values else "light"
    colors = THEME_COLORS[theme]
    
    card_st = {"backgroundColor": colors["card_bg"], "color": colors["text"], **transition_style}
    
    search_panel_st = {
        "position": "absolute", "top": "15px", "left": "15px", "zIndex": "1000",
        "backgroundColor": colors["card_bg"], "color": colors["text"],
        "padding": "15px", "borderRadius": "12px", "boxShadow": "0px 4px 15px rgba(0,0,0,0.2)",
        "width": "320px", **transition_style
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
        {"backgroundColor": colors["card_bg"], "borderRadius": "12px", "color": colors["text"], **transition_style}, 
        search_panel_st, logo_st, search_bar_t2_st,
        card_st, card_st, card_st,
        card_st, card_st, card_st,
        {"backgroundColor": colors["card_bg"], "color": colors["text"], "height": "580px", "position": "relative", **transition_style},
        card_st, card_st, card_st,
        colors["tiles"],
        kpi_couv, kpi_sites, kpi_blanc,
        fig1, fig3, fig4, generate_decision_table(theme, selected_regions, mode=table_mode),
        drilldown_text, btn_reset_style
    )

@app.callback(
    [Output("kpi-distance", "children"), Output("kpi-intermodal", "children"), Output("kpi-statut", "children"),
     Output("map-lines", "children"), Output("map-isochrones", "children"), Output("map-markers", "children"), Output("map", "viewport")],
    Input("btn-search", "n_clicks"),
    [State("input-depart", "value"), State("input-arrivee", "value")],
    prevent_initial_call=True
)
def update_map(n_clicks, depart, arrivee):
    if not depart or not arrivee: 
        return "-- km", "--", "--", [], [], [], dash.no_update
    try:
        df = pd.read_sql(f"SELECT nom, lat, lon, distance_gare_km FROM lieu WHERE nom IN ('{depart}', '{arrivee}')", engine)
        pt_dep = df[df['nom'] == depart].iloc[0]
        pt_arr = df[df['nom'] == arrivee].iloc[0]
        
        dist = pt_arr['distance_gare_km'] if not pd.isna(pt_arr['distance_gare_km']) else np.sqrt((pt_dep['lat']-pt_arr['lat'])**2 + (pt_dep['lon']-pt_arr['lon'])**2) * 111 
        reco = "Marche à pied" if dist <= 1.5 else "Vélo / Bus" if dist <= 5.0 else "Voiture / Taxi"
        
        bounds = [[min(pt_dep['lat'], pt_arr['lat']), min(pt_dep['lon'], pt_arr['lon'])], [max(pt_dep['lat'], pt_arr['lat']), max(pt_dep['lon'], pt_arr['lon'])]]
        
        return (f"{dist:.1f} km", reco, "Faisable" if dist <= 5 else "Difficile",
                [dl.Polyline(positions=[[pt_dep['lat'], pt_dep['lon']], [pt_arr['lat'], pt_arr['lon']]], color=CARMILLON, weight=4)],
                [dl.Circle(center=[pt_arr['lat'], pt_arr['lon']], radius=5000, color=COLORBLIND_PALETTE[3], fillOpacity=0.2)],
                [dl.Marker(position=[pt_dep['lat'], pt_dep['lon']], children=[dl.Tooltip(f"Départ: {depart}")]), dl.Marker(position=[pt_arr['lat'], pt_arr['lon']], children=[dl.Tooltip(f"Destination: {arrivee}")])],
                dict(bounds=bounds, transition="flyTo"))
    except Exception:
        return "Inconnu", "Voiture", "Données manquantes", [], [], [], dash.no_update

if __name__ == "__main__":
    app.run(debug=True)