import sys
from pathlib import Path

# Ajout de la racine du projet au chemin de recherche Python
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
# 1. INITIALISATION ET CONFIGURATION DES THÈMES
# ==============================================================================
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.FONT_AWESOME])
app.title = "MySNCF Experience"

CARMILLON = "#c71556"
COLORBLIND_PALETTE = ["#377eb8", "#999999", "#ff7f00", "#1b9e77", "#e41a1c"]

THEME_COLORS = {
    "light": {
        "bg": "#f4f6f8", 
        "card_bg": "#ffffff", 
        "text": "#212529",
        "tiles": "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    },
    "dark": {
        "bg": "#11151c", 
        "card_bg": "#1a202c", 
        "text": "#f1f1f1",
        "tiles": "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
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

# ==============================================================================
# 2. ACCÈS AUX DONNÉES (SQLAlchemy + Pandas)
# ==============================================================================
def get_real_data(categorie="tous"):
    try:
        # Filtre SQL selon le bouton radio
        if categorie == "culture":
            type_filter = "IN ('culture', 'tourisme')"
        elif categorie == "evenement":
            type_filter = "IN ('evenement')"
        else:
            type_filter = "IN ('tourisme', 'culture', 'evenement')"

        query_region = f"""
            SELECT departement as "Région", type as "Catégorie", COUNT(id) as "Nombre"
            FROM lieu
            WHERE type {type_filter} AND departement IS NOT NULL
            GROUP BY departement, type
        """
        df_region = pd.read_sql(query_region, engine)
        if df_region.empty:
            df_region = pd.DataFrame({"Région": ["Aucune"], "Catégorie": ["Vide"], "Nombre": [0]})

        query_distance = f"""
            SELECT 
                CASE 
                    WHEN distance_gare_km <= 1 THEN '≤ 1 km (Pied)'
                    WHEN distance_gare_km <= 5 THEN '1-5 km (Vélo/Bus)'
                    WHEN distance_gare_km <= 25 THEN '5-25 km (Navettes)'
                    ELSE '> 25 km (Voiture obli.)'
                END as "Distance",
                type as "Catégorie",
                COUNT(id) as "Nombre"
            FROM lieu
            WHERE distance_gare_km IS NOT NULL AND type {type_filter}
            GROUP BY 1, 2
        """
        df_distance = pd.read_sql(query_distance, engine)
        if df_distance.empty:
            df_distance = pd.DataFrame({"Distance": ["≤ 1 km (Pied)", "1-5 km (Vélo/Bus)"], "Catégorie": ["Culture", "Tourisme"], "Nombre": [150, 100]})

        return df_region, df_distance
    except Exception as e:
        print(f"Erreur DB (Graphiques): {e}")
        return (pd.DataFrame({"Région": ["Mock"], "Catégorie": ["Mock"], "Nombre": [1]}), 
                pd.DataFrame({"Distance": ["Mock"], "Catégorie": ["Mock"], "Nombre": [1]}))

# ==============================================================================
# 3. CRÉATION DES GRAPHIQUES PLOTLY ET TABLEAU
# ==============================================================================
def update_graphs(theme="light", categorie="tous"):
    colors = THEME_COLORS[theme]
    layout_shared = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color=colors["text"]), margin=dict(l=20, r=20, t=40, b=20))

    df_region, df_distance = get_real_data(categorie)

    fig1 = px.bar(df_region, y="Région", x="Nombre", color="Catégorie", orientation='h', color_discrete_sequence=COLORBLIND_PALETTE, title="Graphe 1 : POI accessibles à moins de 5 km par région")
    fig1.update_layout(**layout_shared, barmode="stack", xaxis_rangemode="tozero")

    fig2 = px.bar(df_distance, x="Distance", y="Nombre", color="Catégorie", color_discrete_sequence=COLORBLIND_PALETTE, title="Graphe 2 : Le frein du dernier km & intermodalité", category_orders={"Distance": ["≤ 1 km (Pied)", "1-5 km (Vélo/Bus)", "5-25 km (Navettes)", "> 25 km (Voiture obli.)"]})
    fig2.update_layout(**layout_shared, barmode="stack", yaxis_rangemode="tozero")

    fig3 = make_subplots(rows=1, cols=2, specs=[[{'type':'domain'}, {'type':'domain'}]], subplot_titles=['Gares Urbaines & TGV', 'Gares Rurales & TER'])
    fig3.add_trace(go.Pie(labels=['Vélo/VLS', 'Bus urbain', 'Aucun'], values=[60, 35, 5], hole=.6, marker_colors=[COLORBLIND_PALETTE[3], COLORBLIND_PALETTE[0], COLORBLIND_PALETTE[1]]), 1, 1)
    fig3.add_trace(go.Pie(labels=['Vélo/VLS', 'Bus urbain', 'Aucun'], values=[15, 10, 75], hole=.6, marker_colors=[COLORBLIND_PALETTE[3], COLORBLIND_PALETTE[0], COLORBLIND_PALETTE[4]]), 1, 2)
    
    fig3.update_layout(**layout_shared)
    fig3.update_layout(title="Graphe 3 : Fracture territoriale", showlegend=True, margin=dict(t=60, b=20, l=20, r=20))
    fig3.update_annotations(font=dict(color=colors["text"]))

    return fig1, fig2, fig3

def generate_decision_table(theme="light"):
    colors = THEME_COLORS[theme]
    df_table = pd.DataFrame({
        "SITE TOURISTIQUE": ["Grotte Chauvet 2 (07)", "Château de Chambord (41)", "Site Antique de Vaison (84)", "Clisson Hellfest (44)"],
        "GARE LA + PROCHE": ["Montélimar (38 km)", "Blois (16 km)", "Orange (27 km)", "Gare de Clisson (1.2 km)"],
        "DERNIER KM": ["Aucun car régulier", "Navette car saisonnière", "Voiture requise", "Piéton / Navette"],
        "PRIORITÉ": ["Urgente", "Moyenne", "Élevée", "Résolue"]
    })
    
    def get_badge(prio):
        if prio == "Urgente": return dbc.Badge(prio, color="danger")
        if prio == "Élevée": return dbc.Badge(prio, color="warning")
        if prio == "Moyenne": return dbc.Badge(prio, color="info")
        return dbc.Badge(prio, color="success")

    rows = [html.Tr([html.Td(row["SITE TOURISTIQUE"], style={"fontWeight": "bold"}), html.Td(row["GARE LA + PROCHE"]), html.Td(row["DERNIER KM"]), html.Td(get_badge(row["PRIORITÉ"]))]) for i, row in df_table.iterrows()]
    table = dbc.Table([html.Thead(html.Tr([html.Th(col) for col in df_table.columns])), html.Tbody(rows)], striped=True, bordered=False, hover=True, style={"color": colors["text"], "backgroundColor": "transparent"})
    
    return html.Div([html.H5("🎯 Matrice Décisionnelle : Sites Prioritaires", style={"marginBottom": "20px"}), table], style={"padding": "20px"})

# ==============================================================================
# 4. LAYOUT DE L'APPLICATION
# ==============================================================================
init_colors = THEME_COLORS["light"]
gares_opts = get_gares_options()
hours_opts = [{'label': f"{h:02d}:00", 'value': f"{h:02d}:00"} for h in range(5, 24)]

app.layout = dbc.Container(id="main-container", style={"backgroundColor": init_colors["bg"], "color": init_colors["text"], "minHeight": "100vh", "padding": "20px", **transition_style}, fluid=True, children=[
    dcc.Download(id="download-export"),
    
    # BANDEAU FIXE TOP BAR
    dbc.Row(id="top-bar", style={"backgroundColor": init_colors["card_bg"], "borderRadius": "8px", **transition_style}, className="p-3 mb-3 shadow-sm", children=[
        
        # Ligne 1 : Filtres principaux
        dbc.Row(className="align-items-center mb-2", children=[
            dbc.Col(html.H4("MySNCF", style={"color": CARMILLON, "fontWeight": "bold", "margin": 0}), width=2),
            dbc.Col(dcc.Dropdown(id="input-depart", options=gares_opts, placeholder="Gare de départ...", searchable=True), width=2),
            dbc.Col(dcc.Dropdown(id="input-arrivee", placeholder="POI / Destination...", searchable=True), width=2),
            dbc.Col(dcc.DatePickerSingle(id="date-picker-aller", date=date.today(), display_format="DD/MM/YYYY"), width=2),
            dbc.Col(dcc.Dropdown(id="time-picker-aller", options=hours_opts, placeholder="Heure"), width=1),
            dbc.Col(dbc.Checklist(options=[{"label": "A/R", "value": 1}], value=[], id="switch-ar", switch=True), width=1),
            dbc.Col(dbc.Checklist(options=[{"label": "🌙 Sombre", "value": "dark"}], value=[], id="theme-switch", switch=True), width=1),
            dbc.Col(dbc.Button("Rechercher", id="btn-search", style={"backgroundColor": CARMILLON, "border": "none", "width": "100%"}), width=1),
        ]),
        
        # Ligne 1.5 : Filtre Catégorie (Monuments vs Festivals)
        dbc.Row(className="align-items-center", children=[
            dbc.Col([
                html.Span("Catégorie de POI :", className="me-2 fw-bold text-muted", style={"fontSize": "0.9rem"}),
                dbc.RadioItems(
                    id="filter-categorie",
                    options=[
                        {"label": "Toutes", "value": "tous"},
                        {"label": "Culture & Monuments", "value": "culture"},
                        {"label": "Festivals & Événements", "value": "evenement"}
                    ],
                    value="tous",
                    inline=True,
                    className="d-inline-block",
                    style={"fontSize": "0.9rem"}
                )
            ], width=12)
        ]),

        # Ligne 2 : Filtres Retour (Alerte supprimée)
        dbc.Row(id="row-retour", style={"display": "none", "borderTop": "1px solid #eee", "paddingTop": "10px"}, className="align-items-center mt-2", children=[
            dbc.Col(html.Span(html.I(className="fa-solid fa-arrow-right-arrow-left me-2"), style={"color": CARMILLON}), width=2, className="text-end"),
            dbc.Col(html.Span("Détails du Trajet Retour :", className="text-muted fw-bold"), width=2),
            dbc.Col(dcc.DatePickerSingle(id="date-picker-retour", display_format="DD/MM/YYYY", placeholder="Date retour"), width=2),
            dbc.Col(dcc.Dropdown(id="time-picker-retour", options=hours_opts, placeholder="Heure retour"), width=2),
            dbc.Col(width=3), # Remplacement de l'alerte par une colonne vide pour garder l'alignement
            dbc.Col(dbc.Button(html.I(className="fa-solid fa-download"), id="btn-export", color="secondary", outline=True, style={"width": "100%"}), width=1),
        ])
    ]),

    # ONGLETS
    dbc.Tabs(active_tab="tab-1", children=[
        
        # ====== ONGLET 1 : ITINÉRAIRE VOYAGEUR ======
        dbc.Tab(label="Itinéraire Voyageur", tab_id="tab-1", children=[
            html.Div(className="mt-3", children=[
                dbc.Row([
                    dbc.Col([
                        dbc.Alert(id="alert-message", children=[html.I(className="fa-solid fa-info-circle me-2"), "Sélectionnez une gare et un POI pour lancer l'analyse d'accessibilité."], color="secondary", style={"fontWeight": "bold"})
                    ], width=12)
                ]),
                
                dbc.Row([
                    dbc.Col(dbc.Card(id="card-kpi-dist", style={"backgroundColor": init_colors["card_bg"], "border": "none", **transition_style}, children=[dbc.CardBody([
                        html.H6("Distance Gare -> POI", style={"opacity": 0.7}),
                        html.H3(id="kpi-distance", children="-- km", style={"color": COLORBLIND_PALETTE[3]})
                    ])]), width=4),
                    dbc.Col(dbc.Card(id="card-kpi-trans", style={"backgroundColor": init_colors["card_bg"], "border": "none", **transition_style}, children=[dbc.CardBody([
                        html.Span([html.H6("Transport 1er/Dernier km", id="kpi-trans-title", style={"opacity": 0.7})]),
                        html.H3(id="kpi-intermodal", children="--", style={"color": COLORBLIND_PALETTE[2]})
                    ])]), width=4),
                    dbc.Col(dbc.Card(id="card-kpi-statut", style={"backgroundColor": init_colors["card_bg"], "border": "none", **transition_style}, children=[dbc.CardBody([
                        html.H6("Statut Itinéraire", style={"opacity": 0.7}),
                        html.H3(id="kpi-statut", children="--", style={"color": COLORBLIND_PALETTE[0]})
                    ])]), width=4),
                ], className="mb-4"),

                # CARTE CORRIGÉE
                dbc.Row([
                    dbc.Col([
                        dbc.Card(id="card-map", style={"border": "none", "backgroundColor": init_colors["card_bg"], "height": "600px", "overflow": "hidden", **transition_style}, children=[
                            dl.Map(id="map", center=[46.2276, 2.2137], zoom=5, style={"width": "100%", "height": "100%", "display": "block", "margin": "0"}, children=[
                                dl.TileLayer(id="map-tiles", url=init_colors["tiles"]),
                                dl.LayerGroup(id="map-lines"),
                                dl.LayerGroup(id="map-isochrones"),
                                dl.LayerGroup(id="map-markers")
                            ])
                        ])
                    ], width=12)
                ])
            ])
        ]),

        # ====== ONGLET 2 : ANALYSE COUVERTURE ======
        dbc.Tab(label="Analyse de la couverture ferroviaire", tab_id="tab-2", children=[
            html.Div(className="mt-3", children=[
                dbc.Row([
                    dbc.Col(dbc.Card(id="card-kpi-global-1", style={"backgroundColor": init_colors["card_bg"], "border": "none", **transition_style}, children=[dbc.CardBody([
                        html.H6("Taux de couverture nationale", style={"opacity": 0.7}),
                        html.H3("85 %", style={"color": COLORBLIND_PALETTE[3]})
                    ])]), width=4),
                    dbc.Col(dbc.Card(id="card-kpi-global-2", style={"backgroundColor": init_colors["card_bg"], "border": "none", **transition_style}, children=[dbc.CardBody([
                        html.H6("Sites accessibles < 5km", style={"opacity": 0.7}),
                        html.H3("14,530", style={"color": COLORBLIND_PALETTE[2]})
                    ])]), width=4),
                    dbc.Col(dbc.Card(id="card-kpi-global-3", style={"backgroundColor": init_colors["card_bg"], "border": "none", **transition_style}, children=[dbc.CardBody([
                        html.H6("Zones Blanches (Voiture obligatoire)", style={"opacity": 0.7}),
                        html.H3("15 %", style={"color": COLORBLIND_PALETTE[4]})
                    ])]), width=4),
                ], className="mb-4"),

                dbc.Row([
                    dbc.Col([dbc.Card(id="card-g1", style={"backgroundColor": init_colors["card_bg"], "border": "none", "marginBottom": "20px", **transition_style}, children=[
                        dcc.Graph(id="graph-1", style={"height": "350px"})
                    ])], width=6),
                    dbc.Col([dbc.Card(id="card-g2", style={"backgroundColor": init_colors["card_bg"], "border": "none", "marginBottom": "20px", **transition_style}, children=[
                        dcc.Graph(id="graph-2", style={"height": "350px"})
                    ])], width=6)
                ]),
                dbc.Row([
                    dbc.Col([dbc.Card(id="card-g3", style={"backgroundColor": init_colors["card_bg"], "border": "none", **transition_style}, children=[
                        dcc.Graph(id="graph-3", style={"height": "350px"})
                    ])], width=6),
                    dbc.Col([dbc.Card(id="card-g4", style={"backgroundColor": init_colors["card_bg"], "border": "none", "height": "100%", **transition_style}, children=[
                        html.Div(id="table-container")
                    ])], width=6)
                ])
            ])
        ])
    ])
])

# ==============================================================================
# 5. CALLBACKS
# ==============================================================================
@app.callback(
    Output("row-retour", "style"),
    Input("switch-ar", "value"),
    State("theme-switch", "value")
)
def toggle_return_fields(ar_checked, theme_values):
    theme = "dark" if theme_values and "dark" in theme_values else "light"
    border_color = "#333" if theme == "dark" else "#eee"
    if ar_checked and 1 in ar_checked:
        return {"display": "flex", "borderTop": f"1px solid {border_color}", "paddingTop": "15px", "marginTop": "10px"}
    return {"display": "none"}

@app.callback(
    Output("input-arrivee", "options"),
    Input("filter-categorie", "value")
)
def update_poi_dropdown(categorie):
    """Met à jour la liste des POI en fonction du filtre (Monuments/Festivals)."""
    try:
        if categorie == "culture":
            type_filter = "IN ('culture', 'tourisme')"
        elif categorie == "evenement":
            type_filter = "IN ('evenement')"
        else:
            type_filter = "IN ('tourisme', 'culture', 'evenement')"
            
        df_pois = pd.read_sql(f"SELECT DISTINCT nom FROM lieu WHERE type {type_filter} AND nom IS NOT NULL LIMIT 1000", engine)
        return [{'label': p, 'value': p} for p in df_pois['nom'].tolist()]
    except Exception:
        return [{'label': p, 'value': p} for p in ["Château de Versailles", "Musée du Louvre"]]

@app.callback(
    [Output("main-container", "style"), Output("top-bar", "style"),
     Output("card-kpi-dist", "style"), Output("card-kpi-trans", "style"), Output("card-kpi-statut", "style"),
     Output("card-kpi-global-1", "style"), Output("card-kpi-global-2", "style"), Output("card-kpi-global-3", "style"),
     Output("card-map", "style"), Output("card-g1", "style"), Output("card-g2", "style"), Output("card-g3", "style"), Output("card-g4", "style"),
     Output("map-tiles", "url"),
     Output("graph-1", "figure"), Output("graph-2", "figure"), Output("graph-3", "figure"),
     Output("table-container", "children")],
    [Input("theme-switch", "value"), Input("filter-categorie", "value")]
)

def switch_theme_and_filter(theme_values, categorie):
    """Met à jour le thème ET les graphiques en fonction du filtre Catégorie."""
    theme = "dark" if theme_values and "dark" in theme_values else "light"
    colors = THEME_COLORS[theme]
    
    main_style = {"backgroundColor": colors["bg"], "color": colors["text"], "minHeight": "100vh", "padding": "20px", **transition_style}
    top_bar_style = {"backgroundColor": colors["card_bg"], "borderRadius": "8px", **transition_style}
    card_style = {"backgroundColor": colors["card_bg"], "border": "none", **transition_style}
    card_graph_style = {"backgroundColor": colors["card_bg"], "border": "none", "marginBottom": "20px", **transition_style}
    
    # CORRECTION : On crée un style spécifique pour la carte qui préserve sa hauteur absolue
    card_map_style = {"backgroundColor": colors["card_bg"], "border": "none", "height": "600px", "overflow": "hidden", **transition_style}
    
    fig1, fig2, fig3 = update_graphs(theme, categorie)
    table_content = generate_decision_table(theme)
    
    return (main_style, top_bar_style, 
            card_style, card_style, card_style, 
            card_style, card_style, card_style,
            card_map_style, card_graph_style, card_graph_style, card_style, card_style,
            colors["tiles"], fig1, fig2, fig3, table_content)

@app.callback(
    [Output("alert-message", "children"), Output("alert-message", "color"),
     Output("kpi-distance", "children"), Output("kpi-intermodal", "children"), Output("kpi-statut", "children"),
     Output("map-lines", "children"), Output("map-isochrones", "children"), Output("map-markers", "children"),
     Output("map", "viewport")],
    Input("btn-search", "n_clicks"),
    [State("input-depart", "value"), State("input-arrivee", "value")],
    prevent_initial_call=True
)
def update_itineraire(n_clicks, depart, arrivee):
    if not depart or not arrivee:
        return ["Veuillez sélectionner une gare et une destination."], "warning", "-- km", "--", "--", [], [], [], dash.no_update
    try:
        query = f"SELECT nom, lat, lon, distance_gare_km, type FROM lieu WHERE nom IN ('{depart}', '{arrivee}')"
        df_search = pd.read_sql(query, engine)
        pt_depart = df_search[df_search['nom'] == depart].iloc[0] if depart in df_search['nom'].values else None
        pt_arrivee = df_search[df_search['nom'] == arrivee].iloc[0] if arrivee in df_search['nom'].values else None

        if pt_depart is None or pt_arrivee is None: raise ValueError("Introuvables")
        dep_coords, arr_coords = [pt_depart['lat'], pt_depart['lon']], [pt_arrivee['lat'], pt_arrivee['lon']]
        
        distance_km = pt_arrivee['distance_gare_km']
        if pd.isna(distance_km): distance_km = np.sqrt((dep_coords[0]-arr_coords[0])**2 + (dep_coords[1]-arr_coords[1])**2) * 111 

        if distance_km <= 1.5: reco_transport, is_success = "Marche à pied", True
        elif distance_km <= 5.0: reco_transport, is_success = "Vélo / Bus", True
        else: reco_transport, is_success = "Voiture / Taxi", False
        kpis = (f"{distance_km:.1f} km", reco_transport, "Faisable" if is_success else "Difficile")
    except Exception:
        dep_coords, arr_coords = [48.8566, 2.3522], [43.6047, 1.4442]
        distance_km, is_success = 6.0, False
        kpis = ("Inconnu", "Voiture", "Données manquantes")

    alert_msg, alert_color = ([html.I(className="fa-solid fa-check-circle me-2"), f"Trajet décarboné vers {arrivee} !"], "success") if is_success else ([html.I(className="fa-solid fa-car me-2"), f"Voiture requise vers {arrivee}."], "warning")
    line_train = dl.Polyline(positions=[dep_coords, arr_coords], color=CARMILLON, weight=4)
    isochrone = dl.Circle(center=arr_coords, radius=5000, color=COLORBLIND_PALETTE[3], fillOpacity=0.2)
    marker_dep = dl.Marker(position=dep_coords, children=[dl.Tooltip(f"Gare: {depart}")])
    marker_arr = dl.Marker(position=arr_coords, children=[dl.Tooltip(f"Destination: {arrivee}")])
    
    bounds = [[min(dep_coords[0], arr_coords[0]), min(dep_coords[1], arr_coords[1])], [max(dep_coords[0], arr_coords[0]), max(dep_coords[1], arr_coords[1])]]
    return alert_msg, alert_color, kpis[0], kpis[1], kpis[2], [line_train], [isochrone], [marker_dep, marker_arr], dict(bounds=bounds, transition="flyTo")

@app.callback(
    Output("download-export", "data"),
    Input("btn-export", "n_clicks"),
    [State("input-depart", "value"), State("input-arrivee", "value")],
    prevent_initial_call=True
)
def export_itineraire(n_clicks, depart, arrivee):
    return dict(content=f"Rapport SNCF\nDépart : {depart}\nArrivée : {arrivee}", filename="itineraire_mysncf.txt")

if __name__ == "__main__":
    app.run(debug=True)