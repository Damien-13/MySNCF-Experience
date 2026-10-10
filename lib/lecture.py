"""Résumés écrits de la page, lus par les lecteurs d'écran (zone d'annonce) et à voix haute par le bouton « Écouter » du dashboard, sans dépendance à Dash.

Chaque résumé ne garde que l'important : le trajet choisi (départ, arrivée, durée, correspondances, étape par étape), le dernier kilomètre et la faisabilité
pour l'onglet Itinéraire ; les trois indicateurs pour l'onglet Analyse. Les phrases sont écrites pour être entendues : pas de flèches, de symboles ni d'unités abrégées.

Usage :
    resume_itineraire(r, {"sens": "aller", "index": 0})      # r : le résultat de lib.itineraire.rechercher(), tel que le garde le dashboard (store-resultat)
    resume_analyse("87,8 %", "278 207", "12,2 %")
"""
import re
from datetime import datetime

PHRASE_ACCUEIL = "Aucune recherche pour l'instant. Choisissez une gare de départ et une destination, puis lancez la recherche."


def nom_parle(nom):
    """Nom d'une gare sans la commune entre parenthèses (« Marseille Saint-Charles (Marseille) » → « Marseille Saint-Charles ») : répétée, elle alourdit la voix."""
    return re.sub(r"\s*\([^)]*\)", "", str(nom)).strip()


def _pluriel(n, mot):
    return f"{n} {mot}{'s' if n > 1 else ''}"


def duree_parlee(secondes):
    """« 5 heures 8 minutes », « 45 minutes » : une durée en secondes, pour être dite."""
    minutes = round(secondes / 60)
    heures, minutes = divmod(minutes, 60)
    if not heures:
        return _pluriel(minutes, "minute")
    return _pluriel(heures, "heure") + (f" {_pluriel(minutes, 'minute')}" if minutes else "")


def heure_parlee(texte):
    """« 08:53 » → « 8 heures 53 », « 14:01 » → « 14 heures 1 », « 14:00 » → « 14 heures » : l'heure d'un horaire « AAAA-MM-JJ HH:MM:SS » (sans zéro devant : une voix dirait « zéro un »)."""
    d = datetime.fromisoformat(str(texte))
    return f"{d.hour} heures" + (f" {d.minute}" if d.minute else "")


def _etape(section):
    """Phrase d'une section d'un trajet : un train ou un car (numéro, gares, horaires), ou une marche d'au moins une minute ; None sinon."""
    if section.get("type") == "public_transport":
        nom = f"{section.get('ligne') or 'Train'} {section.get('numero') or ''}".strip()
        phrase = f"{nom}"
        if section.get("de") and section.get("vers"):
            phrase += f", de {nom_parle(section['de'])} à {nom_parle(section['vers'])}"
        if section.get("depart") and section.get("arrivee"):
            phrase += f", départ à {heure_parlee(section['depart'])}, arrivée à {heure_parlee(section['arrivee'])}"
        if section.get("retard_min"):
            phrase += f", avec {_pluriel(section['retard_min'], 'minute')} de retard"
        return phrase
    if section.get("mode") == "walking" and (section.get("duree_s") or 0) >= 60:
        return f"à pied, {duree_parlee(section['duree_s'])}"
    return None


def resume_trajet(trajet, numero, total):
    """Phrase d'une option : horaires, durée, correspondances, puis les étapes."""
    corr = trajet.get("correspondances")
    phrase = (f"Option {numero} sur {total} : départ à {heure_parlee(trajet['depart'])}, arrivée à {heure_parlee(trajet['arrivee'])}, "
              f"durée {duree_parlee(trajet['duree_s'])}, " + (f"{_pluriel(corr, 'correspondance')}." if corr else "trajet direct."))
    etapes = [e for e in (_etape(s) for s in trajet.get("sections", [])) if e]
    if etapes:
        phrase += " Étapes : " + " ; ".join(etapes) + "."
    co2 = trajet.get("co2_g")
    if co2:
        phrase += f" Émission : {str(round(co2 / 1000, 1)).replace('.', ',')} kilos de CO2 par voyageur."
    return phrase


def resume_itineraire(r, selection=None):
    """Résumé de l'onglet Itinéraire pour un résultat de recherche `r` et l'option choisie `selection` ({"sens": "aller" ou "retour", "index": n})."""
    if not r:
        return PHRASE_ACCUEIL
    if "message" in r:
        return r["message"]
    selection = selection or {"sens": "aller", "index": 0}
    dep, dest, gare = r["depart"], r["destination"], r.get("gare_arrivee")
    retour = selection.get("sens") == "retour" and bool(r.get("trajets_retour"))
    trajets = (r.get("trajets_retour") if retour else r.get("trajets")) or []
    parties = []
    if gare:
        de, vers = (gare, dep) if retour else (dep, gare)
        parties.append(f"{'Retour' if retour else 'Aller'} de {nom_parle(de['nom'])} à {nom_parle(vers['nom'])}.")
    if trajets:
        index = min(selection.get("index", 0), len(trajets) - 1)
        parties.append(f"{_pluriel(len(trajets), 'option')} de trajet. " + resume_trajet(trajets[index], index + 1, len(trajets)))
    elif r.get("erreur_api"):
        parties.append("Les horaires sont indisponibles.")
    elif gare is None:
        parties.append("Aucune gare d'arrivée connue pour ce lieu.")
    elif r.get("meme_gare"):
        parties.append(f"La gare la plus proche de la destination est la gare de départ, {gare['nom']} : aucun train à prendre.")
    elif r.get("periode_invalide"):
        parties.append(str(r["periode_invalide"]))
    else:
        parties.append("Aucun train trouvé pour ce créneau.")
    if gare and r.get("distance_km") is not None:
        km = str(round(r["distance_km"], 1)).replace(".", ",")
        parties.append(f"La destination, {dest['nom']}, est à {km} kilomètres de la gare d'arrivée, {nom_parle(gare['nom'])}.")
    mode, detail = r.get("dernier_km") or (None, None)
    if mode and mode != "--":
        parties.append(f"Pour le dernier kilomètre : {mode.lower()}, {str(detail).replace('(s)', 's')}.")
    if r.get("faisable") is not None:
        parties.append("Le voyage décarboné est " + ("faisable." if r["faisable"] else "difficile."))
    return " ".join(parties)


def resume_analyse(couverture, sites, blanches):
    """Résumé de l'onglet Analyse : les trois indicateurs, tels qu'affichés (textes)."""
    couverture, blanches = (str(v).replace(".", ",") for v in (couverture, blanches))     # virgule décimale : la voix française dit « virgule », pas « point »
    return ("Analyse de la couverture ferroviaire. "
            f"Taux de couverture à moins de 5 kilomètres d'une gare : {couverture}. "
            f"Sites accessibles sans voiture : {sites}. "
            f"Zones blanches, à plus de 15 kilomètres d'une gare : {blanches}.")
