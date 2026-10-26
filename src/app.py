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
from html import escape
from datetime import date
import requests
from dotenv import load_dotenv

# Charge les variables du fichier .env (dont la clé OpenRouter du rapport exporté)
load_dotenv()

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
from lib import analyse, circulations, lecture, sprites, suivi
from lib.itineraire import FENETRE_API_JOURS, options_heures, retour_minimum, RAYON_POI_KM, chercher_destinations, etiquettes_trajets, nom_gare, options_gares, quand_depuis, rechercher, style_dernier_km, tracer_trajet
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
server = app.server        # point d'entrée WSGI pour gunicorn (Docker)

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
        return []

def spinner(texte):
    """Indicateur de chargement : le train au milieu, le texte juste en dessous (sur toute la largeur de la zone qui charge)."""
    return html.Div([
        html.I(className="fa-solid fa-train-subway fa-beat-fade", style={"color": CARMILLON, "fontSize": "2rem"}),
        html.Div(texte, className="mt-2 text-muted fw-bold")
    ], className="d-flex flex-column align-items-center justify-content-center text-center p-3", style={"width": "100%"})

custom_spinner = spinner("Recherche en cours...")
spinner_analyse = spinner("Calcul en cours...")

# ==============================================================================
# 3. MOTEUR ANALYTIQUE (requêtes dans lib/analyse.py)
# ==============================================================================
CATEGORIES_SITES = {"culture": "Musée / culture", "tourisme": "Tourisme", "evenement": "Festival / événement"}
COULEURS_SITES = {"culture": COLORBLIND_PALETTE[0], "tourisme": "#984ea3", "evenement": COLORBLIND_PALETTE[1]}
KPI_VIDE = "—"          # affiché quand aucun site ne correspond ou que la base est indisponible (jamais de chiffres inventés)

def filtres_analyse(categorie, departements, destination, debut, fin):
    """Les filtres de l'onglet Analyse, communs aux KPI, aux trois graphes, au plan d'action et au rapport exporté."""
    if isinstance(departements, str):
        departements = [departements]
    return analyse.Filtres(categorie or "tous", list(departements or []), destination or None, debut, fin)

def figure_vide(message, layout_shared):
    """Graphe sans données : le message dit pourquoi, au lieu d'afficher des valeurs factices."""
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper", font=dict(size=13))
    fig.update_layout(**layout_shared, xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig

def etiquettes_departements(df):
    """Départements nommés sur le graphe 1, choisis d'après les données : les 4 IAF les plus bas, les 2 plus hauts, les 2 plus gros volumes."""
    if len(df) <= 8:
        return set(df["departement"])
    return set(pd.concat([df.nsmallest(4, "iaf"), df.nlargest(2, "iaf"), df.nlargest(2, "sites")])["departement"])

def positions_etiquettes(df, nommes):
    """Position du nom de chaque point du graphe 1 : à gauche pour les plus gros volumes (sinon le nom sort du graphe),
    et en tournant autour du point pour les autres, par IAF croissant, pour que des départements voisins ne se chevauchent pas."""
    autour = ["bottom center", "middle right", "top center", "middle left"]
    droite = df["sites"].quantile(0.9)
    rangs = {c: i for i, c in enumerate(df[df["departement"].isin(nommes)].sort_values("iaf")["departement"])}
    return ["middle left" if s >= droite else autour[rangs.get(c, 0) % len(autour)] for c, s in zip(df["departement"], df["sites"])]

def nom_departement(code):
    code = str(code)
    return DEPARTEMENTS_MAP.get(code.zfill(2) if code.isdigit() else code, code)

def generate_decision_table(theme="light", df_table=None):
    is_dark = theme == "dark"
    if df_table is None or df_table.empty:
        return html.P("Aucun site ne correspond aux filtres, ou la base de données est indisponible.", className="text-muted fst-italic m-2")
    
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

def generate_ai_analysis_summary(dept_label, kpi_couv, kpi_sites, kpi_blanc, df_table):
    """Synthèse du rapport exporté rédigée par l'IA (OpenRouter / GPT-4o) ; sans clé ou en cas d'erreur, synthèse construite à partir des KPI."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if df_table is not None and not df_table.empty:
        site, gare = df_table.iloc[0]["SITE TOURISTIQUE"], df_table.iloc[0]["GARE LA + PROCHE"]
    else:
        site, gare = None, None

    recommandation = (f"Prioriser l'instauration de navettes estivales intermodales sur les sites classés en priorité 'Urgente' (ex: <i>{escape(site)}</i> connecté à <i>{escape(gare)}</i>)."
                      if site else "Aucun site prioritaire ne ressort pour ces filtres.")
    fallback_analysis = f"""
    <ul>
        <li><b>Diagnostic de couverture :</b> Sur le périmètre <i>{escape(dept_label)}</i>, <b>{kpi_couv}</b> des sites sont à 5 km ou moins d'une gare. Un total de <b>{kpi_sites}</b> sites touristiques restent accessibles sans voiture.</li>
        <li><b>Point de vigilance (Zones Blanches) :</b> <b>{kpi_blanc}</b> des sites souffrent d'un enclavement sévère (> 15 km d'une gare), rendant la voiture individuelle quasi obligatoire pour les visiteurs.</li>
        <li><b>Recommandation stratégique :</b> {recommandation}</li>
    </ul>
    """
    if not api_key:
        return fallback_analysis

    try:
        prompt = f"""Tu es un expert stratégique de la Direction TER & Mobilités de la SNCF.
        Rédige une analyse synthétique et percutante en 3 puces HTML (<ul><li>...</li></ul>) pour le rapport exécutif du périmètre '{dept_label}'.
        Données :
        - Sites à 5 km ou moins d'une gare : {kpi_couv}
        - Sites accessibles sans voiture : {kpi_sites}
        - Zones blanches (> 15km) : {kpi_blanc}
        - Site le plus enclavé : {f"{site} ({gare})" if site else "aucun"}
        Sois concis, professionnel et orienté plan d'action transporteur."""

        res = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://mysncf-experience.sncf.fr",
                "X-Title": "MySNCF Experience",
                "Content-Type": "application/json"
            },
            json={
                "model": "openai/gpt-4o",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3
            },
            timeout=8
        )
        if res.status_code == 200:
            return res.json()["choices"][0]["message"]["content"]
        return fallback_analysis
    except Exception:
        return fallback_analysis

# ==============================================================================
# 4. LAYOUT DE L'APPLICATION (SINGLE SCREEN)
# ==============================================================================
HAUTEUR_CARTE = "max(640px, calc(100vh - 240px))"      # toute la hauteur de l'écran sous les KPI, pour ne pas avoir à descendre
# Panneau des trajets (par-dessus la carte, à droite du panneau de recherche) et bouton pour le rouvrir.
STYLE_PANNEAU = {"position": "absolute", "top": "16px", "right": "16px", "width": "420px", "maxHeight": "calc(100% - 32px)", "overflowY": "auto", "overflowX": "hidden", "zIndex": "1000",
                 "borderRadius": "15px", "boxShadow": "0px 4px 15px rgba(0,0,0,0.3)"}
STYLE_OUVRIR = {"position": "absolute", "top": "16px", "right": "16px", "zIndex": "1000", "backgroundColor": CARMILLON, "border": "none", "fontWeight": "bold",
                "boxShadow": "0px 4px 15px rgba(0,0,0,0.3)"}
init_colors = THEME_COLORS["light"]
gares_opts = get_gares_options()
departements_opts = get_departements_options()
hours_opts = options_heures(None, None)

def mise_en_page():
    """Reconstruite à chaque ouverture de la page : les dates par défaut sont celles du jour, pas celles du démarrage du serveur."""
    return dbc.Container(id="main-container", style={"backgroundColor": init_colors["bg"], "color": init_colors["text"], "minHeight": "100vh", "padding": "12px 20px", **transition_style}, fluid=True, children=[
        html.A("Aller au contenu", href="#contenu", className="visually-hidden-focusable"),      # premier élément atteint au clavier : saute le bandeau
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
        dcc.Store(id="store-js-lecture"),
        dcc.Store(id="store-js-lecture-onglet"),
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
                            dbc.Tab(label="Guide & Lexique", tab_id="tab-3", tab_style={"cursor": "pointer"}),
                        ]
                    ),
                ], className="d-flex align-items-center"),
                width="auto"
            ),
            dbc.Col(
                html.Div([
                    html.Button([html.I(className="fa-solid fa-volume-high me-2", **{"aria-hidden": "true"}), html.Span("Écouter", className="texte-ecouter")], id="btn-ecouter", n_clicks=0,
                                type="button", className="btn btn-outline-secondary btn-sm fw-bold", title="Lire à voix haute le résumé de la page (trajet choisi ou indicateurs)",
                                **{"aria-pressed": "false"}),
                    dbc.Checklist(options=[{"label": "☀️ Clair / 🌙 Sombre", "value": "dark"}], value=[], id="theme-switch", switch=True, className="fw-bold d-flex justify-content-end mb-0"),
                ], className="d-flex align-items-center gap-3"),
                width="auto"
            ),
        ]),

        html.Div(id="contenu", tabIndex=-1, style={"outline": "none"}),            # cible du lien « Aller au contenu »

        # CONTENU DE L'ONGLET 1 (ITINÉRAIRE)
        html.Div(id="tab-1-content", style={"display": "none"}, role="region", **{"aria-label": "Itinéraire voyageur"}, children=[
            html.Div(id="lecture-itineraire", children=lecture.PHRASE_ACCUEIL, className="visually-hidden", role="status", **{"aria-live": "polite", "aria-atomic": "true"}),
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
                            html.Div(style={"position": "relative"}, role="region",
                                     **{"aria-label": "Recherche et carte du trajet (le résumé écrit du trajet est annoncé après chaque recherche)"}, children=[
                                        
                                # PANNEAU RECHERCHE FLOTTANT (Onglet 1)
                                html.Div(id="search-panel", style={
                                    "position": "absolute", "top": "20px", "left": "20px", "zIndex": "1000",
                                    "backgroundColor": init_colors["card_bg"], "color": init_colors["text"],
                                    "padding": "20px", "borderRadius": "15px", "boxShadow": "0px 4px 15px rgba(0,0,0,0.2)",
                                    "width": "340px", **transition_style
                                }, children=[
                                    html.H5(html.I(className="fa-solid fa-route me-2"), className="mb-2", style={"color": CARMILLON}),
                                            
                                    html.Label("Départ :", htmlFor="input-depart", className="fw-bold mb-1", style={"fontSize": "0.9rem"}),
                                    dcc.Dropdown(id="input-depart", options=gares_opts, placeholder="Gare de départ...", searchable=True, className="mb-2"),
                                            
                                    html.Label("Destination :", htmlFor="input-arrivee", className="fw-bold mb-1", style={"fontSize": "0.9rem"}),
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
                                        html.Div(id="options-trajets", children=html.Div("Choisissez une gare de départ et une destination, puis lancez la recherche.", className="text-muted")),       # le chargement s'affiche au milieu de la carte
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
        html.Div(id="tab-2-content", style={"display": "block"}, role="region", **{"aria-label": "Analyse de la couverture ferroviaire"}, children=[
            html.Div(id="lecture-analyse", className="visually-hidden", role="status", **{"aria-live": "polite", "aria-atomic": "true"}),
            # BARRE DE RECHERCHE & FILTRES
            dbc.Card(id="tab2-search-bar", className="dash-card mb-3", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], **transition_style}, children=[
                dbc.CardBody(className="py-2 px-3", children=[
                    dbc.Row(className="g-2 align-items-end", children=[
                        dbc.Col([
                            html.Label([html.I(className="fa-solid fa-flag-checkered me-1"), "Destination"], htmlFor="t2-arrivee", className="fw-bold mb-1", style={"fontSize": "0.8rem"}),
                            dcc.Dropdown(options=[], placeholder="Tapez un nom de site...", searchable=True, id="t2-arrivee")
                        ], width=4),
                    
                        dbc.Col([
                            html.Label([html.I(className="fa-solid fa-map me-1"), "Région / Dép."], htmlFor="t2-region", className="fw-bold mb-1", style={"fontSize": "0.8rem"}),
                            dcc.Dropdown(options=departements_opts, placeholder="Toutes...", id="t2-region", multi=True)
                        ], width=4),
                    
                        dbc.Col([
                            html.Label([html.I(className="fa-regular fa-calendar-days me-1"), "Période (événements)"], htmlFor="t2-periode-range", className="fw-bold mb-1", style={"fontSize": "0.8rem"}),
                            html.Div(dcc.DatePickerRange(
                                id="t2-periode-range",
                                start_date=date.today(),
                                end_date=date.today() + timedelta(days=364),
                                display_format="DD/MM/YYYY",
                                start_date_placeholder_text="Du",
                                end_date_placeholder_text="Au"
                            ), style={"width": "100%"})
                        ], width=4),
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
            dcc.Loading(custom_spinner=spinner_analyse, children=[
                html.Div(id="t2-content", children=[
                    dbc.Row(className="g-3 mb-3", children=[
                        dbc.Col(dbc.Card(id="card-kpi-global-1", className="kpi-card", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "borderTopColor": "#10b981", **transition_style}, children=[dbc.CardBody(className="py-2 px-3", children=[
                            html.Div([
                                html.H6("Sites à 5 km ou moins d'une gare", className="text-uppercase text-muted fw-bold m-0 me-1", style={"fontSize": "0.7rem"}),
                                html.I(className="fa-solid fa-circle-info text-muted", id="tooltip-kpi-1-target", style={"fontSize": "0.75rem", "cursor": "pointer"}),
                                dbc.Tooltip("Part des sites (culture, tourisme, événements de la période) situés à 5 km ou moins, à vol d'oiseau, de la gare la plus proche.", target="tooltip-kpi-1-target", placement="top")
                            ], className="d-flex align-items-center mb-1"),
                            html.H4(id="t2-kpi-couverture", children=KPI_VIDE, style={"color": "#10b981", "fontWeight": "bold", "margin": "0"})
                        ])]), width=4),
                    
                        dbc.Col(dbc.Card(id="card-kpi-global-2", className="kpi-card", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "borderTopColor": COLORBLIND_PALETTE[1], **transition_style}, children=[dbc.CardBody(className="py-2 px-3", children=[
                            html.Div([
                                html.H6("Sites accessibles sans voiture", className="text-uppercase text-muted fw-bold m-0 me-1", style={"fontSize": "0.7rem"}),
                                html.I(className="fa-solid fa-circle-info text-muted", id="tooltip-kpi-2-target", style={"fontSize": "0.75rem", "cursor": "pointer"}),
                                dbc.Tooltip("Nombre de sites à 5 km ou moins d'une gare : joignables à pied, à vélo ou en bus depuis le train. Les stations vélo et arrêts ne sont pas comptés comme sites.", target="tooltip-kpi-2-target", placement="top")
                            ], className="d-flex align-items-center mb-1"),
                            html.H4(id="t2-kpi-sites", children=KPI_VIDE, style={"color": COLORBLIND_PALETTE[1], "fontWeight": "bold", "margin": "0"})
                        ])]), width=4),
                    
                        dbc.Col(dbc.Card(id="card-kpi-global-3", className="kpi-card", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], "borderTopColor": CARMILLON, **transition_style}, children=[dbc.CardBody(className="py-2 px-3", children=[
                            html.Div([
                                html.H6("Zones blanches (> 15 km d'une gare)", className="text-uppercase text-muted fw-bold m-0 me-1", style={"fontSize": "0.7rem"}),
                                html.I(className="fa-solid fa-circle-info text-muted", id="tooltip-kpi-3-target", style={"fontSize": "0.75rem", "cursor": "pointer"}),
                                dbc.Tooltip("Part des sites à plus de 15 km d'une gare, ou sans gare connue : il faut une navette dédiée ou une voiture.", target="tooltip-kpi-3-target", placement="top")
                            ], className="d-flex align-items-center mb-1"),
                            html.H4(id="t2-kpi-blanches", children=KPI_VIDE, style={"color": CARMILLON, "fontWeight": "bold", "margin": "0"})
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
                                        html.H6([html.I(className="fa-solid fa-sliders me-2", style={"color": CARMILLON}), "Outils d'Aide à la Décision Métier"], className="fw-bold m-0 text-uppercase", style={"fontSize": "0.85rem"}),
                                        html.Small("Consultez la feuille de route opérationnelle ou téléchargez la synthèse exécutive.", className="text-muted")
                                    ], width=6),
                                    dbc.Col([
                                        dbc.Button([html.I(className="fa-solid fa-list-check me-2"), "Plan d'Action (Top 10)"], id="btn-open-modal", style={"backgroundColor": CARMILLON, "border": "none", "fontWeight": "bold", "fontSize": "0.85rem", "marginRight": "10px"}, n_clicks=0),
                                        dbc.Tooltip("Ouvre la matrice décisionnelle complète détaillant les gares et sites prioritaires.", target="btn-open-modal", placement="top"),
                                    
                                        dbc.Button([html.I(className="fa-solid fa-file-arrow-down me-2"), "Exporter le Rapport (avec IA)"], id="btn-export-report", color="dark", outline=True, style={"fontWeight": "bold", "fontSize": "0.85rem"}, n_clicks=0),
                                        dbc.Tooltip("Génère un rapport exécutif complet incluant une synthèse automatique rédigée par l'IA (OpenRouter / GPT-4o).", target="btn-export-report", placement="top")
                                    ], width=6, className="d-flex justify-content-end align-items-center")
                                ])
                            ]),
                            width=12
                        )
                    ])
                ])
            ])
        ]),

        # CONTENU DE L'ONGLET 3 (GUIDE & LEXIQUE MÉTIER)
        html.Div(id="tab-3-content", style={"display": "none"}, role="region", **{"aria-label": "Guide et lexique"}, children=[
            dbc.Card(id="card-guide", className="dash-card p-4", style={"backgroundColor": init_colors["card_bg"], "color": init_colors["text"], **transition_style}, children=[
                html.H4([html.I(className="fa-solid fa-book-bookmark me-2", style={"color": CARMILLON}), "Guide Utilisateur & Notice Méthodologique"], className="fw-bold mb-3"),
                html.Hr(),
                dbc.Row([
                    dbc.Col([
                        html.H5("📘 Lexique des Indicateurs", className="fw-bold mb-3", style={"color": CARMILLON}),
                        html.Ul([
                            html.Li([html.B("IAF (Indice d'Accessibilité Ferroviaire) : "), "Calculé comme le pourcentage de sites touristiques (POI, monuments, festivals) situés dans un rayon ≤ 5 km d'une gare SNCF."]),
                            html.Li([html.B("Premier / Dernier Kilomètre : "), "Segment de trajet entre la gare d'arrivée et le site destination, nécessitant de la marche, un VLS (Vélo en Libre-Service), un car ou une voiture."]),
                            html.Li([html.B("Zones Blanches (> 15 km) : "), "Territoires enclavés où l'offre ferroviaire seule est insuffisante et impose un rabattement routier."]),
                        ])
                    ], width=6),
                    dbc.Col([
                        html.H5("🛠️ Provenance & Qualité des Données", className="fw-bold mb-3", style={"color": CARMILLON}),
                        html.Ul([
                            html.Li([html.B("SNCF Open Data : "), "Jeux de données de géolocalisation des lieux, gares et arrêts routiers."]),
                            html.Li([html.B("DATAtourisme & Ministère de la Culture : "), "Inventaire national des monuments, musées et programmation événementielle."]),
                            html.Li([html.B("Dernière mise à jour BDD : "), f"{date.today().strftime('%B %Y')} (Base SQLite locale)."]),
                        ])
                    ], width=6),
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
    [State("t2-region", "value"), State("filter-categorie", "value"), State("t2-arrivee", "value"),
     State("t2-periode-range", "start_date"), State("t2-periode-range", "end_date"),
     State("t2-kpi-couverture", "children"), State("t2-kpi-sites", "children"), State("t2-kpi-blanches", "children")],
    prevent_initial_call=True
)
def export_report(n_clicks, regions, categorie, destination, debut, fin, kpi_couv, kpi_sites, kpi_blanc):
    if not n_clicks:
        return dash.no_update
    
    dept_label = "National (Toute la France)"
    if regions:
        dept_label = ", ".join([DEPARTEMENTS_MAP.get(str(r).zfill(2), str(r)) for r in (regions if isinstance(regions, list) else [regions])])
    
    try:
        df_table = analyse.plan_action(engine, filtres_analyse(categorie, regions, destination, debut, fin), mode="pires")
    except Exception:
        df_table = pd.DataFrame(columns=["SITE TOURISTIQUE", "GARE LA + PROCHE", "DERNIER KM", "PRIORITÉ"])

    # Génération du paragraphe d'analyse rédigé par IA via OpenRouter (GPT-4o)
    ai_summary_html = generate_ai_analysis_summary(dept_label, kpi_couv, kpi_sites, kpi_blanc, df_table)

    table_rows_html = "".join([
        f"<tr><td style='padding:10px;border-bottom:1px solid #eee;'><b>{escape(r['SITE TOURISTIQUE'])}</b></td><td style='padding:10px;border-bottom:1px solid #eee;'>{escape(r['GARE LA + PROCHE'])}</td><td style='padding:10px;border-bottom:1px solid #eee;'>{r['DERNIER KM']}</td><td style='padding:10px;border-bottom:1px solid #eee;color:#c71556;'><b>{r['PRIORITÉ']}</b></td></tr>"
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
            .kpi-container {{ display: flex; gap: 20px; margin-bottom: 25px; }}
            .kpi-box {{ flex: 1; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); border-top: 5px solid #c71556; }}
            .kpi-title {{ font-size: 0.8rem; text-transform: uppercase; color: #6c757d; font-weight: bold; }}
            .kpi-value {{ font-size: 2rem; font-weight: bold; margin-top: 5px; color: #11151c; }}
            .ai-box {{ background: white; padding: 20px; border-radius: 10px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); margin-bottom: 30px; border-left: 5px solid #10b981; }}
            table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 10px rgba(0,0,0,0.05); margin-top: 15px; }}
            th {{ background: #343a40; color: white; padding: 12px; text-align: left; font-size: 0.85rem; text-transform: uppercase; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1 style="margin:0; font-size: 1.8rem;">MySNCF Experience — Rapport Métier d'Accessibilité</h1>
            <p style="margin:8px 0 0 0; opacity: 0.9; font-size: 1rem;">Périmètre : {escape(dept_label)}{escape(" | Destination : " + destination) if destination else ""}{f" | Événements du {debut[:10]} au {fin[:10]}" if debut and fin else ""} | Édité le : {date.today().strftime('%d/%m/%Y')}</p>
        </div>
        
        <h2 style="font-size: 1.2rem; color: #495057;">Chiffres Clés d'Accessibilité Ferroviaire</h2>
        <div class="kpi-container">
            <div class="kpi-box" style="border-top-color: #10b981;">
                <div class="kpi-title">Sites à 5 km ou moins d'une gare</div>
                <div class="kpi-value" style="color: #10b981;">{kpi_couv}</div>
            </div>
            <div class="kpi-box" style="border-top-color: #ff7f00;">
                <div class="kpi-title">Sites accessibles sans voiture</div>
                <div class="kpi-value" style="color: #ff7f00;">{kpi_sites}</div>
            </div>
            <div class="kpi-box" style="border-top-color: #c71556;">
                <div class="kpi-title">Zones blanches (> 15 km d'une gare)</div>
                <div class="kpi-value" style="color: #c71556;">{kpi_blanc}</div>
            </div>
        </div>
        
        <h2 style="font-size: 1.2rem; color: #495057;">Synthèse Décisionnelle (Analyse IA GPT-4o / OpenRouter)</h2>
        <div class="ai-box">
            {ai_summary_html}
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
    [Output("tab-1-content", "style"), Output("tab-2-content", "style"), Output("tab-3-content", "style")],
    Input("tabs-navigation", "active_tab")
)
def switch_tab_content(active_tab):
    if active_tab == "tab-1":
        return {"display": "block"}, {"display": "none"}, {"display": "none"}
    elif active_tab == "tab-3":
        return {"display": "none"}, {"display": "none"}, {"display": "block"}
    return {"display": "none"}, {"display": "block"}, {"display": "none"}

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
     Output("card-g4-saison", "style"), Output("card-outils", "style"), Output("card-guide", "style"),
     Output("map-tiles", "url"), Output("card-map", "className"),
     Output("t2-kpi-couverture", "children"), Output("t2-kpi-sites", "children"), Output("t2-kpi-blanches", "children"),
     Output("graph-1", "figure"), Output("graph-3", "figure"), Output("graph-4", "figure"),
     Output("table-container", "children"),
     Output("drilldown-text", "children"), Output("btn-reset-drilldown", "style"),
     Output("card-results", "style"), Output("t2-region", "value")],
    [Input("theme-switch", "value"), Input("filter-categorie", "value"), 
     Input("btn-search-t2", "n_clicks"), Input("t2-table-mode", "value"),
     Input("graph-1", "clickData"), Input("btn-reset-drilldown", "n_clicks")],
    [State("t2-region", "value"), State("t2-arrivee", "value"), State("t2-periode-range", "start_date"), State("t2-periode-range", "end_date")]
)
def update_ui_and_graphs(theme_values, categorie, t2_clicks, table_mode, click_data, reset_clicks, t2_regions, t2_arrivee, t2_debut, t2_fin):
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
    
    # Drill-down via clic sur le graphe 1 : le département cliqué devient le filtre de tout l'onglet (et s'affiche dans « Région / Dép. »)
    selected_regions = t2_regions
    triggered_id = ctx.triggered_id
    
    if triggered_id == "btn-reset-drilldown":
        selected_regions = None
    elif triggered_id == "graph-1" and click_data and "points" in click_data:
        clicked_code = click_data["points"][0].get("customdata", [None])[0]
        if clicked_code:
            selected_regions = [str(clicked_code)]

    # Status du filtre actif (Signifiant visuel Roll-up)
    if selected_regions:
        label_reg = ", ".join([nom_departement(r) for r in (selected_regions if isinstance(selected_regions, list) else [selected_regions])])
        drilldown_text = f"🎯 Filtre actif : {label_reg}"
        btn_reset_style = {"display": "inline-block", "fontSize": "0.75rem", "padding": "2px 8px"}
    else:
        drilldown_text = "💡 Cliquez sur un point du Graphe 1 pour zoomer (Drill-down)"
        btn_reset_style = {"display": "none", "fontSize": "0.75rem", "padding": "2px 8px"}

    filtres = filtres_analyse(categorie, selected_regions, t2_arrivee, t2_debut, t2_fin)
    try:
        d = analyse.donnees(engine, filtres)
        df_table = analyse.plan_action(engine, filtres, mode=table_mode)
        vide = "Aucun site ne correspond à ces filtres"
    except Exception:
        d, df_table = None, None
        vide = "Base de données indisponible : lancez src/initialize.py"
    kpi = d["kpi"] if d else None
    kpi_couv = f"{kpi['part_sans_voiture']} %" if kpi else KPI_VIDE
    kpi_sites = f"{kpi['sans_voiture']:,}".replace(",", " ") if kpi else KPI_VIDE
    kpi_blanc = f"{kpi['part_zones_blanches']} %" if kpi else KPI_VIDE
    
    # --------------------------------------------------------------------------
    # GRAPHE 1 : Scatter Plot (Pleine Hauteur Gauche)
    # --------------------------------------------------------------------------
    titre1 = "<b>Volume de sites × accessibilité ferroviaire par département</b>"
    df_iaf = d["departements"] if d else pd.DataFrame()
    if df_iaf.empty:
        fig1 = figure_vide(vide, layout_shared)
        fig1.update_layout(title=titre1)
    else:
        df_iaf = df_iaf.sort_values("sites").reset_index(drop=True)
        df_iaf["nom"] = df_iaf["departement"].map(nom_departement)
        nommes = etiquettes_departements(df_iaf)
        df_iaf["etiquette"] = [n.split(" - ", 1)[-1] if c in nommes else "" for c, n in zip(df_iaf["departement"], df_iaf["nom"])]
        fig1 = px.scatter(
            df_iaf, x="sites", y="iaf", text="etiquette", color="iaf",
            custom_data=["departement", "nom"],
            color_continuous_scale="Viridis",          # séquentielle et lisible par les daltoniens (pas de rouge-vert)
            log_x=True,
            title=titre1,
            labels={"sites": "nombre de sites (log)", "iaf": "IAF (0-100)"}
        )
        fig1.update_traces(
            marker=dict(size=12, opacity=0.85, line=dict(width=1, color="DarkSlateGrey")),
            textposition=positions_etiquettes(df_iaf, nommes),
            hovertemplate="<b>%{customdata[1]}</b><br>Sites : %{x}<br>IAF : %{y}<extra></extra>"
        )
        if d["iaf_france"] is not None:
            fig1.add_hline(y=d["iaf_france"], line_dash="dash", line_color="#4b5563", annotation_text=f"France : {d['iaf_france']:.0f}", annotation_position="bottom right")
        fig1.update_layout(
            **layout_shared, showlegend=False, coloraxis_showscale=False,
            clickmode='event+select'
        )

    # --------------------------------------------------------------------------
    # GRAPHE 3 : Répartition par Tranche de Distance (Haut Droite)
    # --------------------------------------------------------------------------
    titre3 = "<b>Répartition des sites par tranche de distance</b>"
    df_distance = d["distances"] if d else pd.DataFrame()
    if df_distance.empty:
        fig3 = figure_vide(vide, layout_shared)
        fig3.update_layout(title=titre3)
    else:
        df_distance = df_distance.assign(categorie=df_distance["type"].map(CATEGORIES_SITES))
        fig3 = px.bar(
            df_distance, x="tranche", y="sites", color="categorie",
            color_discrete_map={CATEGORIES_SITES[t]: c for t, c in COULEURS_SITES.items()},
            title=titre3,
            labels={"tranche": "Transport recommandé", "sites": "Sites", "categorie": "Catégorie"},
            category_orders={"tranche": analyse.TRANCHES, "categorie": list(CATEGORIES_SITES.values())}
        )
        fig3.update_traces(hovertemplate="Catégorie : %{fullData.name}<br>Nombre : %{y}<extra></extra>")
        fig3.update_layout(**layout_shared, barmode="stack", yaxis_rangemode="tozero")

    # --------------------------------------------------------------------------
    # GRAPHE 4 : Saisonnalité Événementielle (Bas Droite)
    # --------------------------------------------------------------------------
    titre4 = "<b>Événements qui commencent chaque mois de la période</b>"
    df_saison = d["saison"] if d else pd.DataFrame()
    if df_saison.empty:
        fig4 = figure_vide("Pas d'événement dans la catégorie choisie" if d and categorie in ("culture", "tourisme") else
                           "Aucun événement pour ces filtres" if d else vide, layout_shared)
        fig4.update_layout(title=titre4)
    else:
        fig4 = px.area(
            df_saison, x="mois", y="evenements", markers=True,
            color_discrete_sequence=[COLORBLIND_PALETTE[1]],
            title=titre4,
            labels={"mois": "Mois", "evenements": "Événements"}
        )
        fig4.update_traces(hovertemplate="Mois : %{x}<br>Événements : %{y}<extra></extra>")
        fig4.update_layout(**layout_shared, yaxis_rangemode="tozero", xaxis_type="category")

    return (
        {"backgroundColor": colors["bg"], "color": colors["text"], "minHeight": "100vh", "padding": "12px 20px", **transition_style},
        colors["root_class"],
        {"backgroundColor": colors["card_bg"], "borderRadius": "12px", "color": colors["text"], **transition_style}, 
        search_panel_st, logo_st, search_bar_t2_st,
        card_iti, card_iti, card_iti,
        card_st, card_st, card_st,
        {"backgroundColor": colors["card_bg"], "color": colors["text"], "border": "none", "height": HAUTEUR_CARTE, "position": "relative", "overflow": "hidden", **transition_style},
        card_st, card_st, card_st, card_st, card_st,
        colors["tiles"], colors["map_class"],
        kpi_couv, kpi_sites, kpi_blanc,
        fig1, fig3, fig4, generate_decision_table(theme, df_table),
        drilldown_text, btn_reset_style, card_iti, selected_regions
    )


@app.callback(
    Output("t2-arrivee", "options"),
    Input("t2-arrivee", "search_value"),
    State("t2-arrivee", "value")
)
def chercher_sites_analyse(recherche, choisi):
    """Le filtre Destination cherche dans tous les sites au fil de la frappe (2 lettres minimum) ; le site choisi reste dans la liste.
    Comme pour l'onglet Itinéraire (_option_destination), chaque option reçoit la saisie comme texte de recherche : le tri est déjà fait côté serveur."""
    try:
        noms = analyse.chercher_sites(engine, recherche)
    except Exception:
        noms = []
    if choisi and choisi not in noms:
        noms = [choisi] + noms
    return [{"label": n, "value": n, "search": recherche or n} for n in noms]

POI_COULEURS = {"culture": COLORBLIND_PALETTE[0], "tourisme": "#984ea3", "evenement": COLORBLIND_PALETTE[1]}
POI_LIBELLES = {"culture": "Musée / culture", "tourisme": "Tourisme", "evenement": "Festival / événement"}
POI_ICONES = {"culture": "fa-landmark", "tourisme": "fa-camera", "evenement": "fa-masks-theater"}
POI_PAR_CATEGORIE = {"tous": ["tourisme", "culture", "evenement"], "culture": ["culture"], "tourisme": ["tourisme"], "evenement": ["evenement"]}


def _duree(secondes):
    h, m = divmod(round(secondes / 60), 60)
    return f"{h} h {m:02d}" if h else f"{m} min"

def _heure(texte):
    return datetime.fromisoformat(texte).strftime("%H:%M")

def _horaire_section(etape):
    """« · 08:53 → 09:20 » : départ et arrivée d'un train ou d'un car dans le détail d'une option (rien pour la marche ou sans horaire)."""
    if etape["marche"] or not (etape.get("depart") and etape.get("arrivee")):
        return ""
    return f" · {_heure(etape['depart'])}→{_heure(etape['arrivee'])}"

def _echantillon(couleur, tirets):
    """Petit trait qui reprend la couleur et le motif d'un service (pour reconnaître la ligne sur la carte sans se fier à la couleur)."""
    base = {"display": "inline-block", "width": "30px", "height": "5px", "marginRight": "6px", "verticalAlign": "middle", "borderRadius": "3px"}
    if not tirets:
        return html.Span(style={**base, "backgroundColor": couleur})
    arrets, position = [], 0.0
    for i, v in enumerate(float(v) * 1.6 for v in tirets.split()):         # rangs pairs : trait, rangs impairs : vide
        arrets.append(f"{couleur if i % 2 == 0 else 'transparent'} {position:.0f}px {position + v:.0f}px")
        position += v
    return html.Span(style={**base, "background": f"repeating-linear-gradient(90deg, {', '.join(arrets)})"})

def _ligne_etape(t):
    """Une étape dans le détail d'une option : le service et son numéro (« TGV INOUI 6120 », « Bus AIX - AEROPORT », « À pied · 6 min »), ses horaires
    et son retard, puis les gares de départ et d'arrivée."""
    retard = t.get("retard_min") or 0
    gares = f"{nom_gare(t['de'])} → {nom_gare(t['vers'])}" if t.get("de") and t.get("vers") and nom_gare(t["de"]) != nom_gare(t["vers"]) else ""
    return html.Div(className="mb-1", style={"fontSize": "0.8rem"}, children=[
        html.Div(style={"whiteSpace": "nowrap", "overflow": "hidden", "textOverflow": "ellipsis"}, children=[
            _echantillon(t["style"]["couleur"], t["style"]["tirets"]), html.Span(t["libelle"], className="fw-bold" if not t["marche"] else ""),
            html.Span(_horaire_section(t), style={"opacity": 0.7}),
            *([html.Span(f" · +{retard} min", className="fw-bold", style={"color": "#c0392b"})] if retard else [])]),
        *([html.Div(gares, style={"opacity": 0.7, "paddingLeft": "36px", "fontSize": "0.74rem", "whiteSpace": "nowrap", "overflow": "hidden", "textOverflow": "ellipsis"})] if gares else []),
    ])

def _carte_option(i, trajet, actif, traces, etiquettes=(), fin=None):
    """Un bloc cliquable : étiquettes (le plus rapide…), heures, durée, correspondances, puis chaque étape (service, numéro, horaires, gares).
    `fin` : (libellé, détail) du dernier kilomètre jusqu'à la destination, ajouté après le dernier train à l'aller."""
    puces = [html.Span([html.I(className=f"fa-solid {icone} me-1"), texte], className="badge rounded-pill me-1", style={"backgroundColor": couleur, "fontSize": "0.68rem"})
             for texte, icone, couleur in etiquettes]
    lignes = [_ligne_etape(t) for t in traces]
    if fin:
        lignes.append(html.Div(className="mb-1", style={"fontSize": "0.8rem"}, children=[
            html.Div([_echantillon(fin[2]["couleur"], fin[2]["tirets"]), html.Span(fin[0])]),
            html.Div(fin[1], style={"opacity": 0.7, "paddingLeft": "36px", "fontSize": "0.74rem"})]))
    co2 = trajet.get("co2_g")
    en_retard = [t for t in traces if not t["marche"] and (t.get("retard_min") or 0) > 0]
    retards = "Retard annoncé : " + ", ".join(f"{t['retard_min']} min sur {t['libelle']}" for t in en_retard) if en_retard else ""
    return html.Div(style={"flex": "0 0 auto"}, children=html.Div(id={"type": "option", "index": i}, n_clicks=0, role="button", tabIndex=0, **{"aria-pressed": "true" if actif else "false"}, children=[
        *([html.Div(puces, className="mb-2")] if puces else []),
        html.Div([html.Span(f"Option {i + 1}", className="badge me-2", style={"backgroundColor": CARMILLON if actif else "#6c757d"}),
                  html.Span(f"{_heure(trajet['depart'])} → {_heure(trajet['arrivee'])}", className="fs-6 fw-bold")]),
        html.Div(f"{_duree(trajet['duree_s'])} · " + (f"{trajet['correspondances']} corresp." if trajet["correspondances"] else "direct")
                 + (f" · {co2 / 1000:.1f} kg CO₂e" if co2 else ""), className="mb-1", style={"opacity": 0.8, "fontSize": "0.78rem"}),
        *([html.Div(retards, className="mb-2 fw-bold", style={"color": "#c0392b", "fontSize": "0.78rem"})] if retards else []),
        *(lignes if actif else []),                   # le détail des étapes n'apparaît qu'au clic sur l'option
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
    Output("lecture-itineraire", "children"),
    [Input("store-resultat", "data"), Input("store-selection", "data")]
)
def resumer_itineraire(r, selection):
    """Résumé écrit du trajet choisi : annoncé par les lecteurs d'écran à chaque recherche ou changement d'option, et lu par le bouton « Écouter »."""
    return lecture.resume_itineraire(r, selection)


@app.callback(
    Output("lecture-analyse", "children"),
    [Input("t2-kpi-couverture", "children"), Input("t2-kpi-sites", "children"), Input("t2-kpi-blanches", "children")]
)
def resumer_analyse(couverture, sites, blanches):
    """Résumé écrit des trois indicateurs de l'onglet Analyse (même usage que le résumé de l'itinéraire)."""
    return lecture.resume_analyse(couverture, sites, blanches)


# Le bouton « Écouter » lit le résumé de l'onglet ouvert à voix haute ; changer d'onglet arrête la lecture (src/assets/lecture.js).
app.clientside_callback(
    ClientsideFunction(namespace="lecture", function_name="ecouter"),
    Output("store-js-lecture", "data"),
    Input("btn-ecouter", "n_clicks"),
    State("tabs-navigation", "active_tab"),
    prevent_initial_call=True
)
app.clientside_callback(
    ClientsideFunction(namespace="lecture", function_name="arreter"),
    Output("store-js-lecture-onglet", "data"),
    Input("tabs-navigation", "active_tab"),
    prevent_initial_call=True
)


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

    traces_options = [tracer_trajet(t, reseau_ferre, *liaison, engine=engine) for t in trajets]
    traces = traces_options[index] if trajets else tracer_trajet(None, reseau_ferre, *liaison, engine=engine)
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
        mode_fin, detail_fin = r["dernier_km"]
        fin = None if retour or mode_fin == "--" or r["destination"]["type"] == "ville" else (f"{mode_fin} · {detail_fin}" if mode_fin == "Marche à pied" else mode_fin,
                                                        f"{nom_gare(gare['nom'])} → {r['destination']['nom']}", style_dernier_km(mode_fin))
        blocs = html.Div([_carte_option(i, t, i == index, traces_options[i], etiquettes[i], fin) for i, t in enumerate(trajets)],
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
    pas = [t["points"] for t in traces if t["marche"] and t["style"]["cle"] == "pied"]  # trajets à pied, dessinés en empreintes de pas
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
    """Image d'un train ou d'un bus, recadrée en mémoire à partir de assets/train/ ou assets/bus/ (voir lib/sprites.py)."""
    png = sprites.sprite_png(cle) if cle in sprites.IMAGES or cle in sprites.BUS_IMAGES else None
    if png is None:
        abort(404)
    return Response(png, mimetype="image/png", headers={"Cache-Control": "public, max-age=86400"})


if __name__ == "__main__":
    app.run(
        host=os.getenv("DASH_HOST", "127.0.0.1"),
        port=int(os.getenv("DASH_PORT", "8050")),
        debug=os.getenv("DASH_DEBUG", "1").lower() not in ("0", "false", "no", ""),
    )