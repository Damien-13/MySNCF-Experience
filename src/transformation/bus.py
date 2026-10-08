"""Transformation des réseaux urbains (bus, tram, métro, bateau…) de 20 agglomérations : GTFS vers reseau, ligne, circulation,
calendrier, arret et passage. Outils communs : gtfs.py.

Usage : python src/transformation/bus.py   (les gares doivent déjà être chargées : voir transformation.py)
Relançable sans risque : chaque réseau est remplacé en entier (tout passe ou rien). Environ 25 millions de passages au total.

Chaque arrêt a son propre lieu (type « arret_bus », quel que soit le mode) avec sa gare la plus proche si elle est à moins de 50 km.
Il n'est jamais rattaché à une gare : un arrêt « Gare SNCF » d'un réseau urbain est un autre objet que la gare.
Chevauchement avec le GTFS SNCF : aucun risque, aucun de ces fichiers ne contient d'agence SNCF ; les cars TER restent dans sncf.py.
Île-de-France (métro, tram, bus d'IDFM) : pas encore traité.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gtfs
from lieux import lire_gares

# dossier de data/ → (identifiant du réseau, nom)
RESEAUX = {
    "bus_marseille_amp": ("marseille_amp", "Aix-Marseille-Provence"),
    "bus_toulouse_tisseo": ("toulouse_tisseo", "Tisséo (Toulouse)"),
    "bus_bordeaux_tbm": ("bordeaux_tbm", "TBM (Bordeaux)"),
    "bus_nantes_naolib": ("nantes_naolib", "Naolib (Nantes)"),
    "bus_strasbourg_cts": ("strasbourg_cts", "CTS (Strasbourg)"),
    "bus_rennes_star": ("rennes_star", "STAR (Rennes)"),
    "bus_lille_ilevia": ("lille_ilevia", "ilévia (Lille)"),
    "bus_nice_lignes_dazur": ("nice_lignes_dazur", "Lignes d'Azur (Nice)"),
    "bus_rouen_astuce": ("rouen_astuce", "Astuce (Rouen)"),
    "bus_toulon_mistral": ("toulon_mistral", "Mistral (Toulon)"),
    "bus_angers_irigo": ("angers_irigo", "Irigo (Angers)"),
    "bus_tours_fil_bleu": ("tours_fil_bleu", "Fil Bleu (Tours)"),
    "bus_orleans_tao": ("orleans_tao", "TAO (Orléans)"),
    "bus_dijon_divia": ("dijon_divia", "Divia (Dijon)"),
    "bus_brest_bibus": ("brest_bibus", "Bibus (Brest)"),
    "bus_besancon_ginko": ("besancon_ginko", "Ginko (Besançon)"),
    "bus_metz_le_met": ("metz_le_met", "Le Met' (Metz)"),
    "bus_reims_grand_reims": ("reims_grand_reims", "Grand Reims Mobilités"),
    "bus_saint_etienne_stas": ("saint_etienne_stas", "STAS (Saint-Étienne)"),
    "bus_montpellier_tam": ("montpellier_tam", "TaM (Montpellier)"),
}
# route_type GTFS de base ; les types étendus (700 = bus, 900 = tramway…) sont ramenés à leur famille (centaine)
TYPES = {0: "Tramway", 1: "Métro", 2: "Train", 3: "Bus", 4: "Bateau", 5: "Tramway à câble", 6: "Téléphérique", 7: "Funiculaire", 11: "Trolleybus", 12: "Monorail"}
FAMILLES = {1: "Train", 2: "Car", 4: "Métro", 7: "Bus", 8: "Trolleybus", 9: "Tramway", 10: "Bateau", 12: "Bateau", 13: "Téléphérique", 14: "Funiculaire", 15: "Taxi"}


def type_ligne(route_type):
    """« 3 » → Bus ; « 715 » (bus à la demande) → Bus ; « 900 » → Tramway ; inconnu ou vide → Bus."""
    try:
        code = int(route_type)
    except (TypeError, ValueError):
        return "Bus"
    return TYPES.get(code) or FAMILLES.get(code // 100, "Bus")


def nettoyer(brut, reseau_id):
    routes = brut["routes"]
    types = dict(zip(routes["route_id"], routes["route_type"].map(type_ligne)))
    return gtfs.normaliser(brut, reseau_id, types_lignes=types)


def transformer():
    if lire_gares().empty:
        sys.exit("Aucune gare en base : lancer d'abord l'étape gares (python src/transformation/transformation.py)")
    total = [0, 0, 0, 0]
    for dossier, (reseau_id, nom) in RESEAUX.items():
        frames = nettoyer(gtfs.lire(ROOT / "data" / dossier), reseau_id)
        nombres = gtfs.charger(frames, {"id": reseau_id, "nom": nom, "mode": "bus"}, dossier, type_lieu="arret_bus")
        total = [t + n for t, n in zip(total, nombres)]
        print(f"{nom} : {nombres[0]} lignes, {nombres[1]} circulations, {nombres[2]} arrêts, {nombres[3]} passages", flush=True)
    print(f"Bus : {len(RESEAUX)} réseaux, {total[0]} lignes, {total[1]} circulations, {total[2]} arrêts, {total[3]} passages")
    return total


if __name__ == "__main__":
    transformer()
