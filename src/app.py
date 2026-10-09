import sys
import os
from pathlib import Path
import base64

# Ajout de la racine du projet au chemin de recherche Python
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ==============================================================================
# 1. FIX DÉFINITIF POUR L'IMAGE (Encodage Base64)
# ==============================================================================
def get_logo_base64():
    """Lit l'image directement depuis le dossier assets pour éviter les bugs de route Dash."""
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
from dash import dcc, html, Input, Output, State
import dash_bootstrap_components as dbc
import dash_leaflet as dl
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import date

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

CARMILLON = "#c71556"
COLORBLIND_PALETTE = ["#377eb8", "#999999", "#ff7f00", "#1b9e77", "#e41a1c"]

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
        df_gares = pd.read_sql("SELECT DISTINCT nom FROM lieu WHERE type = 'gare' AND nom IS NOT NULL", engine)
        return [{'label': g, 'value': g} for g in df_gares['nom'].tolist()]
    except Exception:
        return [{'label': "Paris Gare de Lyon", 'value': "Paris Gare de Lyon"}]

# Animation de chargement
custom_spinner = html.Div([
    html.I(className="fa-solid fa-train-subway fa-beat-fade me-3", style={"color": CARMILLON, "fontSize": "2rem"}),
    html.Div("Analyse en cours...", className="mt-2 text-muted fw-bold")
], className="text-center p-4")

# Listes d'options pour l'onglet 2
REGIONS = ["Île-de-France", "Auvergne-Rhône-Alpes", "Bourgogne-Franche-Comté", "Bretagne", "Centre-Val de Loire", "Corse", "Grand Est", "Hauts-de-France", "Normandie", "Nouvelle-Aquitaine", "Occitanie", "Pays de la Loire", "Provence-Alpes-Côte d'Azur"]
TRAINS = ["OUIGO", "TGV INOUI", "TER", "Transilien", "RER", "Renfe AVE", "Frecciarossa"]
PERIODES = ["Matin (06h-12h)", "Après-midi (12h-18h)", "Soirée (18h-00h)", "Nuit (00h-06h)"]

# ==============================================================================
# 3. ACCÈS AUX DONNÉES ET GRAPHIQUES
# ==============================================================================
def get_real_data(categorie="tous"):
    try:
        if categorie == "culture": type_filter = "IN ('culture', 'tourisme')"
        elif categorie == "evenement": type_filter = "IN ('evenement')"
        else: type_filter = "IN ('tourisme', 'culture', 'evenement')"

        df_region = pd.read_sql(f"SELECT departement as \"Région\", type as \"Catégorie\", COUNT(id) as \"Nombre\" FROM lieu WHERE type {type_filter} AND departement IS NOT NULL GROUP BY departement, type", engine)
        if df_region.empty: df_region = pd.DataFrame({"Région": ["Aucune"], "Catégorie": ["Vide"], "Nombre": [0]})

        df_distance = pd.read_sql(f"SELECT CASE WHEN distance_gare_km <= 1 THEN '≤ 1 km (Pied)' WHEN distance_gare_km <= 5 THEN '1-5 km (Vélo/Bus)' WHEN distance_gare_km <= 25 THEN '5-25 km (Navettes)' ELSE '> 25 km (Voiture obli.)' END as \"Distance\", type as \"Catégorie\", COUNT(id) as \"Nombre\" FROM lieu WHERE distance_gare_km IS NOT NULL AND type {type_filter} GROUP BY 1, 2", engine)
        if df_distance.empty: df_distance = pd.DataFrame({"Distance": ["≤ 1 km (Pied)", "1-5 km (Vélo/Bus)"], "Catégorie": ["Culture", "Tourisme"], "Nombre": [150, 100]})

        return df_region, df_distance
    except Exception:
        return (pd.DataFrame({"Région": ["Mock"], "Catégorie": ["Mock"], "Nombre": [1]}), pd.DataFrame({"Distance": ["Mock"], "Catégorie": ["Mock"], "Nombre": [1]}))

def update_graphs(theme="light", categorie="tous"):
    colors = THEME_COLORS[theme]
    layout_shared = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color=colors["text"]), margin=dict(l=20, r=20, t=40, b=20))

    fig1 = px.bar(get_real_data(categorie)[0], y="Région", x="Nombre", color="Catégorie", orientation='h', color_discrete_sequence=COLORBLIND_PALETTE, title="Graphe 1 : POI par région (< 5km)")
    fig1.update_layout(**layout_shared, barmode="stack", xaxis_rangemode="tozero")

    fig2 = px.bar(get_real_data(categorie)[1], x="Distance", y="Nombre", color="Catégorie", color_discrete_sequence=COLORBLIND_PALETTE, title="Graphe 2 : Le frein du dernier km", category_orders={"Distance": ["≤ 1 km (Pied)", "1-5 km (Vélo/Bus)", "5-25 km (Navettes)", "> 25 km (Voiture obli.)"]})
    fig2.update_layout(**layout_shared, barmode="stack", yaxis_rangemode="tozero")

    fig3 = make_subplots(rows=1, cols=2, specs=[[{'type':'domain'}, {'type':'domain'}]], subplot_titles=['Gares Urbaines & TGV', 'Gares Rurales & TER'])
    fig3.add_trace(go.Pie(labels=['Vélo/VLS', 'Bus urbain', 'Aucun'], values=[60, 35, 5], hole=.6, marker_colors=[COLORBLIND_PALETTE[3], COLORBLIND_PALETTE[0], COLORBLIND_PALETTE[1]]), 1, 1)
    fig3.add_trace(go.Pie(labels=['Vélo/VLS', 'Bus urbain', 'Aucun'], values=[15, 10, 75], hole=.6, marker_colors=[COLORBLIND_PALETTE[3], COLORBLIND_PALETTE[0], COLORBLIND_PALETTE[4]]), 1, 2)
    fig3.update_layout(**layout_shared, title="Graphe 3 : Fracture territoriale", showlegend=True)
    fig3.update_annotations(font=dict(color=colors["text"]))

    return fig1, fig2, fig3

def generate_decision_table(theme="light"):
    colors = THEME_COLORS[theme]
    is_dark = theme == "dark"
    df_table = pd.DataFrame({
        "SITE TOURISTIQUE": ["Grotte Chauvet 2 (07)", "Château de Chambord (41)", "Site Antique de Vaison (84)", "Clisson (44)"],
        "GARE LA + PROCHE": ["Montélimar (38 km)", "Blois (16 km)", "Orange (27 km)", "Gare de Clisson (1.2 km)"],
        "DERNIER KM": ["Aucun car", "Navette saison", "Voiture requise", "Piéton / Navette"],
        "PRIORITÉ": ["Urgente", "Moyenne", "Élevée", "Résolue"]
    })
    
    def get_badge(prio):
        return dbc.Badge(prio, color="danger" if prio == "Urgente" else "warning" if prio == "Élevée" else "info" if prio == "Moyenne" else "success")

    rows = [html.Tr([html.Td(row["SITE TOURISTIQUE"], style={"fontWeight": "bold"}), html.Td(row["GARE LA + PROCHE"]), html.Td(row["DERNIER KM"]), html.Td(get_badge(row["PRIORITÉ"]))]) for _, row in df_table.iterrows()]
    table = dbc.Table([html.Thead(html.Tr([html.Th(col) for col in df_table.columns])), html.Tbody(rows)], striped=True, bordered=False, hover=True, color="dark" if is_dark else "light")
    return html.Div([html.H5("🎯 Matrice Décisionnelle : Sites Prioritaires", style={"marginBottom": "20px"}), table], style={"padding": "20px"})

# ==============================================================================
# 4. LAYOUT DE L'APPLICATION
# ==============================================================================
init_colors = THEME_COLORS["light"]
gares_opts = get_gares_options()
hours_opts = [{'label': f"{h:02d}:00", 'value': f"{h:02d}:00"} for h in range(5, 24)]

app.layout = dbc.Container(id="main-container", style={"backgroundColor": init_colors["bg"], "color": init_colors["text"], "minHeight": "100vh", "padding": "20px", **transition_style}, fluid=True, children=[
    dcc.Download(id="download-export"),
    
    # BANDEAU TOP BAR ÉPURÉ (Juste Logo et Thème)
    dbc.Row(id="top-bar", style={"backgroundColor": init_colors["card_bg"], "borderRadius": "8px", **transition_style}, className="p-3 mb-4 shadow-sm align-items-center", children=[
        dbc.Col(html.Img(id="logo-img", src=LOGO_SRC, style={"maxHeight": "70px", "objectFit": "contain", "borderRadius": "8px", "padding": "5px"}), width=6, className="text-start"),
        dbc.Col(dbc.Checklist(options=[{"label": "☀️ Clair / 🌙 Sombre", "value": "dark"}], value=[], id="theme-switch", switch=True, className="fw-bold d-flex justify-content-end"), width=6),
    ]),

    # ONGLETS
    dbc.Tabs(id="tabs-navigation", active_tab="tab-1", className="mb-4", children=[
        
        # ====== ONGLET 1 : ITINÉRAIRE ======
        dbc.Tab(label="Itinéraire Voyageur", tab_id="tab-1", children=[
            html.Div(className="mt-3", children=[
                dbc.Row([
                    dbc.Col(dbc.Card(id="card-kpi-dist", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "border": "none", **transition_style}, children=[dbc.CardBody([
                        html.H6("Distance Gare -> Destination", style={"opacity": 0.8}), html.H3(id="kpi-distance", children="-- km", style={"color": COLORBLIND_PALETTE[3]})
                    ])]), width=4),
                    dbc.Col(dbc.Card(id="card-kpi-trans", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "border": "none", **transition_style}, children=[dbc.CardBody([
                        html.H6("Transport 1er/Dernier km", style={"opacity": 0.8}), html.H3(id="kpi-intermodal", children="--", style={"color": COLORBLIND_PALETTE[2]})
                    ])]), width=4),
                    dbc.Col(dbc.Card(id="card-kpi-statut", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "border": "none", **transition_style}, children=[dbc.CardBody([
                        html.H6("Faisabilité Décarbonée", style={"opacity": 0.8}), html.H3(id="kpi-statut", children="--", style={"color": COLORBLIND_PALETTE[0]})
                    ])]), width=4),
                ], className="mb-4"),

                dbc.Row([
                    dbc.Col([
                        dbc.Card(id="card-map", style={"border": "none", "backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "height": "650px", "position": "relative", "overflow": "hidden", **transition_style}, children=[
                            dcc.Loading(custom_spinner=custom_spinner, children=[
                                html.Div(style={"position": "relative"}, children=[
                                    
                                    # PANNEAU RECHERCHE FLOTTANT (Onglet 1)
                                    html.Div(id="search-panel", style={
                                        "position": "absolute", "top": "20px", "left": "20px", "zIndex": "1000",
                                        "backgroundColor": init_colors["card_bg"], "color": init_colors["text"],
                                        "padding": "20px", "borderRadius": "15px", "boxShadow": "0px 4px 15px rgba(0,0,0,0.2)",
                                        "width": "340px", **transition_style
                                    }, children=[
                                        html.H5(html.I(className="fa-solid fa-route me-2"), className="mb-3", style={"color": CARMILLON}),
                                        
                                        html.Label("Départ :", className="fw-bold mb-1", style={"fontSize": "0.9rem"}),
                                        dcc.Dropdown(id="input-depart", options=gares_opts, placeholder="Départ...", searchable=True, className="mb-3"),
                                        
                                        html.Label("Destination :", className="fw-bold mb-1", style={"fontSize": "0.9rem"}),
                                        dcc.Dropdown(id="input-arrivee", placeholder="Destination...", searchable=True, className="mb-3"),
                                        
                                        html.Label("Aller :", className="fw-bold mb-1", style={"fontSize": "0.9rem"}),
                                        dbc.Row(className="g-2 mb-3", children=[
                                            dbc.Col(dcc.DatePickerSingle(id="date-picker-aller", date=date.today(), display_format="DD/MM/YYYY"), width=7),
                                            dbc.Col(dcc.Dropdown(id="time-picker-aller", options=hours_opts, placeholder="Heure"), width=5),
                                        ]),
                                        
                                        dbc.Checklist(options=[{"label": "Trajet Aller/Retour", "value": 1}], value=[], id="switch-ar", switch=True, className="fw-bold mb-2", style={"fontSize": "0.9rem"}),
                                        
                                        html.Div(id="row-retour", style={"display": "none"}, children=[
                                            html.Label("Retour :", className="fw-bold mb-1", style={"fontSize": "0.9rem"}),
                                            dbc.Row(className="g-2 mb-3", children=[
                                                dbc.Col(dcc.DatePickerSingle(id="date-picker-retour", display_format="DD/MM/YYYY", placeholder="Date retour"), width=7),
                                                dbc.Col(dcc.Dropdown(id="time-picker-retour", options=hours_opts, placeholder="Heure"), width=5),
                                            ])
                                        ]),
                                        
                                        html.Hr(className="my-3", style={"opacity": "0.1"}),
                                        
                                        html.Label("Catégorie de POI :", className="fw-bold mb-2", style={"fontSize": "0.9rem"}),
                                        dbc.RadioItems(
                                            id="filter-categorie",
                                            options=[
                                                {"label": html.Span([html.I(className="fa-solid fa-map-location-dot me-2"), "Toutes"]), "value": "tous"},
                                                {"label": html.Span([html.I(className="fa-solid fa-landmark me-2"), "Culture"]), "value": "culture"},
                                                {"label": html.Span([html.I(className="fa-solid fa-masks-theater me-2"), "Festivals"]), "value": "evenement"}
                                            ],
                                            value="tous", className="fw-bold mb-4", style={"fontSize": "0.85rem"}
                                        ),
                                        
                                        dbc.Button([html.I(className="fa-solid fa-magnifying-glass me-2"), "Rechercher"], id="btn-search", style={"backgroundColor": CARMILLON, "border": "none", "width": "100%", "fontWeight": "bold", "padding": "10px"})
                                    ]),

                                    dl.Map(id="map", center=[46.2, 3.5], zoom=5, style={"width": "100%", "height": "650px", "display": "block", "margin": "0"}, children=[
                                        dl.TileLayer(id="map-tiles", url=init_colors["tiles"]),
                                        dl.LayerGroup(id="map-lines"), dl.LayerGroup(id="map-isochrones"), dl.LayerGroup(id="map-markers")
                                    ])
                                ])
                            ])
                        ])
                    ], width=12)
                ])
            ])
        ]),

        # ====== ONGLET 2 : ANALYSE ======
        dbc.Tab(label="Analyse de la couverture ferroviaire", tab_id="tab-2", children=[
            html.Div(className="mt-3", children=[
                
                # NOUVELLE BANDE DE RECHERCHE HORIZONTALE (Onglet 2)
                dbc.Card(id="tab2-search-bar", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "borderRadius": "15px", "border": "none", "boxShadow": "0px 4px 15px rgba(0,0,0,0.05)", "marginBottom": "25px", **transition_style}, children=[
                    dbc.CardBody([
                        dbc.Row(className="g-3 align-items-end", children=[
                            dbc.Col([
                                html.Label([html.I(className="fa-solid fa-location-dot me-2"), "Départ"], className="fw-bold mb-1", style={"fontSize": "0.85rem"}),
                                dcc.Dropdown(options=gares_opts, placeholder="Départ...", searchable=True, id="t2-depart")
                            ], width=2),
                            dbc.Col([
                                html.Label([html.I(className="fa-solid fa-flag-checkered me-2"), "Destination"], className="fw-bold mb-1", style={"fontSize": "0.85rem"}),
                                dcc.Dropdown(placeholder="Destination...", searchable=True, id="t2-arrivee")
                            ], width=2),
                            dbc.Col([
                                html.Label([html.I(className="fa-solid fa-map me-2"), "Région"], className="fw-bold mb-1", style={"fontSize": "0.85rem"}),
                                dcc.Dropdown(options=[{'label': r, 'value': r} for r in REGIONS], placeholder="Toutes...", id="t2-region")
                            ], width=2),
                            dbc.Col([
                                html.Label([html.I(className="fa-regular fa-calendar-days me-2"), "Date"], className="fw-bold mb-1", style={"fontSize": "0.85rem"}),
                                html.Div(dcc.DatePickerSingle(id="t2-date", date=date.today(), display_format="DD/MM/YYYY"), style={"width": "100%"})
                            ], width=2),
                            dbc.Col([
                                html.Label([html.I(className="fa-solid fa-clock me-2"), "Période"], className="fw-bold mb-1", style={"fontSize": "0.85rem"}),
                                dcc.Dropdown(options=[{'label': p, 'value': p} for p in PERIODES], placeholder="Toutes...", id="t2-periode")
                            ], width=2),
                            dbc.Col([
                                html.Label([html.I(className="fa-solid fa-train me-2"), "Type de train"], className="fw-bold mb-1", style={"fontSize": "0.85rem"}),
                                dcc.Dropdown(options=[{'label': t, 'value': t} for t in TRAINS], placeholder="Tous...", id="t2-train", multi=True)
                            ], width=2),
                        ]),
                        dbc.Row(className="mt-4", children=[
                            dbc.Col(
                                dbc.Button([html.I(className="fa-solid fa-filter me-2"), "Filtrer l'analyse"], id="btn-search-t2", style={"backgroundColor": CARMILLON, "border": "none", "fontWeight": "bold", "padding": "10px 30px", "borderRadius": "8px"}),
                                width=12, className="text-center"
                            )
                        ])
                    ])
                ]),

                # KPIs et Graphiques existants
                dbc.Row([
                    dbc.Col(dbc.Card(id="card-kpi-global-1", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "border": "none", **transition_style}, children=[dbc.CardBody([
                        html.H6("Taux de couverture nationale", style={"opacity": 0.8}), html.H3("85 %", style={"color": COLORBLIND_PALETTE[3]})
                    ])]), width=4),
                    dbc.Col(dbc.Card(id="card-kpi-global-2", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "border": "none", **transition_style}, children=[dbc.CardBody([
                        html.H6("Sites accessibles < 5km", style={"opacity": 0.8}), html.H3("14,530", style={"color": COLORBLIND_PALETTE[2]})
                    ])]), width=4),
                    dbc.Col(dbc.Card(id="card-kpi-global-3", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "border": "none", **transition_style}, children=[dbc.CardBody([
                        html.H6("Zones Blanches (Voiture obligatoire)", style={"opacity": 0.8}), html.H3("15 %", style={"color": COLORBLIND_PALETTE[4]})
                    ])]), width=4),
                ], className="mb-4"),

                dbc.Row([
                    dbc.Col([dbc.Card(id="card-g1", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "border": "none", "marginBottom": "20px", **transition_style}, children=[dcc.Graph(id="graph-1", style={"height": "350px"})])], width=6),
                    dbc.Col([dbc.Card(id="card-g2", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "border": "none", "marginBottom": "20px", **transition_style}, children=[dcc.Graph(id="graph-2", style={"height": "350px"})])], width=6)
                ]),
                dbc.Row([
                    dbc.Col([dbc.Card(id="card-g3", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "border": "none", **transition_style}, children=[dcc.Graph(id="graph-3", style={"height": "350px"})])], width=6),
                    dbc.Col([dbc.Card(id="card-g4", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "border": "none", "height": "100%", **transition_style}, children=[html.Div(id="table-container")])], width=6)
                ])
            ])
        ])
    ])
])

# ==============================================================================
# 5. CALLBACKS
# ==============================================================================
@app.callback(Output("row-retour", "style"), Input("switch-ar", "value"))
def toggle_return_fields(ar_checked):
    return {"display": "block"} if ar_checked and 1 in ar_checked else {"display": "none"}

@app.callback(Output("input-arrivee", "options"), Input("filter-categorie", "value"))
def update_poi_dropdown(categorie):
    try:
        type_filter = "IN ('culture', 'tourisme')" if categorie == "culture" else "IN ('evenement')" if categorie == "evenement" else "IN ('tourisme', 'culture', 'evenement')"
        return [{'label': p, 'value': p} for p in pd.read_sql(f"SELECT DISTINCT nom FROM lieu WHERE type {type_filter} AND nom IS NOT NULL LIMIT 1000", engine)['nom'].tolist()]
    except: return [{'label': p, 'value': p} for p in ["Château de Versailles", "Musée du Louvre"]]

@app.callback(
    [Output("main-container", "style"), Output("top-bar", "style"), Output("search-panel", "style"), Output("logo-img", "style"),
     Output("tab2-search-bar", "style"),
     Output("card-kpi-dist", "style"), Output("card-kpi-trans", "style"), Output("card-kpi-statut", "style"),
     Output("card-kpi-global-1", "style"), Output("card-kpi-global-2", "style"), Output("card-kpi-global-3", "style"),
     Output("card-map", "style"), Output("card-g1", "style"), Output("card-g2", "style"), Output("card-g3", "style"), Output("card-g4", "style"),
     Output("map-tiles", "url"),
     Output("graph-1", "figure"), Output("graph-2", "figure"), Output("graph-3", "figure"),
     Output("table-container", "children")],
    [Input("theme-switch", "value"), Input("filter-categorie", "value")]
)
def update_ui_and_graphs(theme_values, categorie):
    theme = "dark" if theme_values and "dark" in theme_values else "light"
    colors = THEME_COLORS[theme]
    
    card_st = {"backgroundColor": colors["card_bg"], "color": colors["text"], "border": "none", **transition_style}
    
    search_panel_st = {
        "position": "absolute", "top": "20px", "left": "20px", "zIndex": "1000",
        "backgroundColor": colors["card_bg"], "color": colors["text"],
        "padding": "20px", "borderRadius": "15px", "boxShadow": "0px 4px 15px rgba(0,0,0,0.2)",
        "width": "340px", **transition_style
    }
    
    search_bar_t2_st = {
        "backgroundColor": colors["card_bg"], "color": colors["text"],
        "borderRadius": "15px", "border": "none", "boxShadow": "0px 4px 15px rgba(0,0,0,0.05)",
        "marginBottom": "25px", **transition_style
    }
    
    logo_bg = "rgba(255, 255, 255, 0.9)" if theme == "dark" else "transparent"
    logo_st = {"maxHeight": "70px", "objectFit": "contain", "borderRadius": "8px", "padding": "5px", "backgroundColor": logo_bg, **transition_style}
    
    fig1, fig2, fig3 = update_graphs(theme, categorie)
    
    return (
        {"backgroundColor": colors["bg"], "color": colors["text"], "minHeight": "100vh", "padding": "20px", **transition_style},
        {"backgroundColor": colors["card_bg"], "borderRadius": "8px", "color": colors["text"], **transition_style}, 
        search_panel_st, logo_st, search_bar_t2_st,
        card_st, card_st, card_st,
        card_st, card_st, card_st,
        {"backgroundColor": colors["card_bg"], "color": colors["text"], "border": "none", "height": "650px", "position": "relative", "overflow": "hidden", **transition_style},
        {"backgroundColor": colors["card_bg"], "color": colors["text"], "border": "none", "marginBottom": "20px", **transition_style},
        {"backgroundColor": colors["card_bg"], "color": colors["text"], "border": "none", "marginBottom": "20px", **transition_style},
        card_st, card_st,
        colors["tiles"], fig1, fig2, fig3, generate_decision_table(theme)
    )

@app.callback(
    [Output("kpi-distance", "children"), Output("kpi-intermodal", "children"), Output("kpi-statut", "children"),
     Output("map-lines", "children"), Output("map-isochrones", "children"), Output("map-markers", "children"), Output("map", "viewport")],
    Input("btn-search", "n_clicks"),
    [State("input-depart", "value"), State("input-arrivee", "value")],
    prevent_initial_call=True
)
def update_map(n_clicks, depart, arrivee):
    if not depart or not arrivee: return "-- km", "--", "--", [], [], [], dash.no_update
    try:
        df = pd.read_sql(f"SELECT nom, lat, lon, distance_gare_km FROM lieu WHERE nom IN ('{depart}', '{arrivee}')", engine)
        pt_dep, pt_arr = df[df['nom'] == depart].iloc[0], df[df['nom'] == arrivee].iloc[0]
        
        dist = pt_arr['distance_gare_km'] if not pd.isna(pt_arr['distance_gare_km']) else np.sqrt((pt_dep['lat']-pt_arr['lat'])**2 + (pt_dep['lon']-pt_arr['lon'])**2) * 111 
        reco = "Marche à pied" if dist <= 1.5 else "Vélo / Bus" if dist <= 5.0 else "Voiture / Taxi"
        
        bounds = [[min(pt_dep['lat'], pt_arr['lat']), min(pt_dep['lon'], pt_arr['lon'])], [max(pt_dep['lat'], pt_arr['lat']), max(pt_dep['lon'], pt_arr['lon'])]]
        
        return (f"{dist:.1f} km", reco, "Faisable" if dist <= 5 else "Difficile",
                [dl.Polyline(positions=[[pt_dep['lat'], pt_dep['lon']], [pt_arr['lat'], pt_arr['lon']]], color=CARMILLON, weight=4)],
                [dl.Circle(center=[pt_arr['lat'], pt_arr['lon']], radius=5000, color=COLORBLIND_PALETTE[3], fillOpacity=0.2)],
                [dl.Marker(position=[pt_dep['lat'], pt_dep['lon']], children=[dl.Tooltip(f"Départ: {depart}")]), dl.Marker(position=[pt_arr['lat'], pt_arr['lon']], children=[dl.Tooltip(f"Destination: {arrivee}")])],
                dict(bounds=bounds, transition="flyTo"))
    except:
        return "Inconnu", "Voiture", "Données manquantes", [], [], [], dash.no_update

if __name__ == "__main__":
    app.run(debug=True)