/*
 * Animation des trains sur la carte (onglet Itinéraire voyageur). Dash charge ce fichier tout seul (dossier assets de src/).
 *
 * Pourquoi côté navigateur : le serveur ne peut renvoyer une position qu'une fois par seconde, ce qui donne un mouvement saccadé.
 * Ici, chaque image de l'écran (60 par seconde) recalcule la position du train à partir des horaires reçus.
 *
 * Données (envoyées par src/app.py, voir lib/suivi.py pour le même calcul côté serveur) :
 *   etapes : un objet par étape du trajet choisi : points [[lat, lon], …], depart / arrivee (« AAAA-MM-JJ HH:MM:SS »), retard_min, libelle,
 *            de / vers (gares), marche, style {couleur, libelle}, sprite (image du train ou null), longueur_m, rapport, acc (accélération en m/s²).
 *   tous   : les trains en circulation sur tout le réseau (même forme, depart / arrivee en secondes depuis l'époque, id = la circulation).
 *   horloge : {mode: "reel"} ou {mode: "sim", t0_reel: secondes} (le trajet défile à VITESSE_SIM fois la vitesse réelle).
 *
 * Mouvement : entre deux gares le train accélère, roule à sa vitesse de croisière, puis freine (profil trapézoïdal calé sur l'horaire),
 * donc sa vitesse affichée varie vraiment : 0 à quai, maximale au milieu du trajet.
 *
 * Taille : un train fait sa longueur réelle (100 à 200 m) à l'échelle de la carte, donc il grandit en zoomant et rapetisse en dézoomant.
 * C'est toujours son image. Seuls les trains du trajet choisi (ou simulé) ne descendent jamais sous LONGUEUR_MIN_PX, pour rester visibles ;
 * les trains « tous réseaux » rapetissent presque à l'échelle exacte (plancher de LONGUEUR_MIN_TOUS_PX).
 *
 * Clic sur un train (une zone de clic plus large que l'image, pour viser un train vu de loin) : zoom sur lui, fenêtre d'informations
 * (vitesse, distance restante), et la caméra le suit : d'une gare à la suivante, à quai pendant l'arrêt, et d'un train au suivant
 * pour un trajet avec correspondance. Elle s'arrête à la fermeture de la fenêtre ou quand on déplace la carte à la main.
 */
(function () {
  const VITESSE_SIM = 120;           // 1 seconde réelle = 2 minutes de trajet, comme lib/suivi.py
  const LONGUEUR_MIN_PX = 16;        // plancher de longueur à l'écran pour les trains du TRAJET CHOISI : sans lui, ils disparaîtraient en dézoomant (0 = échelle exacte)
  const LONGUEUR_MIN_TOUS_PX = 6;    // plancher beaucoup plus petit pour les trains « tous réseaux » : de petits repères en dézoomant, sans encombrer la carte (0 = échelle exacte, ils disparaissent)
  const LARGEUR_MAX_PX = 700;
  const ETIREMENT = 1.8;             // les trains vus du dessus sont très fins : on les élargit un peu pour qu'on les reconnaisse
  const ZOOM_SUIVI = 12;             // niveau de zoom atteint en cliquant sur un train (on ne dézoome jamais : si on est déjà plus près, on reste)
  const LISSAGE_CAP_M = 60;          // le cap du train est calculé sur ± cette distance : les virages tournent progressivement
  const PAS_TOUS_MS = 200;           // les trains « tous réseaux » sont recalculés 5 fois par seconde (il y en a des milliers)
  const PAS_POPUP_MS = 250;          // la fenêtre d'informations est remise à jour 4 fois par seconde
  const PATIENCE_SUIVI_MS = 6000;    // temps pendant lequel on garde la caméra sur un train qui n'est plus dans les données (rafraîchissement en cours)
  const PAS_EMPREINTE_PX = 30;       // distance à l'écran entre deux foulées (l'icône d'empreintes montre déjà le pied gauche et le pied droit)
  const ANGLE_EMPREINTE = 0;         // l'icône d'empreintes de Font Awesome pointe vers l'est : on la tourne de l'angle du chemin
  const R_TERRE = 6371008.8;

  const S = (window.__trains = window.__trains || {
    carte: null, etapes: [], horloge: { mode: "reel" }, tous: [], circ: new Map(), toutesActives: false,
    pas: [], couchePas: null, sel: {}, tousMarq: {}, tousData: {}, suivi: null, perdu: null, pauseSuivi: 0, ouvrir: null, trame: null, dernierTous: 0, dernierPopup: 0,
  });

  // ---------- Accès à la carte Leaflet (dash-leaflet ne la donne pas : on la cherche dans l'arbre React) ----------
  function estCarte(o) {
    return o && typeof o.getZoom === "function" && typeof o.getCenter === "function" && o._container;
  }
  function trouverCarte() {
    if (S.carte && S.carte._container && S.carte._container.isConnected) return S.carte;
    const conteneur = document.querySelector("#map");
    if (!conteneur) return null;
    const cle = Object.keys(conteneur).find((k) => k.startsWith("__reactFiber"));
    let fibre = cle && conteneur[cle];
    let trouvee = null;
    const chercher = (o, profondeur) => {
      if (!o || profondeur > 3 || trouvee) return;
      if (estCarte(o)) { trouvee = o; return; }
      if (typeof o === "object") {
        for (const k of Object.keys(o).slice(0, 20)) { try { chercher(o[k], profondeur + 1); } catch (e) { /* propriété inaccessible */ } }
      }
    };
    for (let n = 0; fibre && n < 8 && !trouvee; n++, fibre = fibre.return) {
      for (let h = fibre.memoizedState, i = 0; h && i < 30 && !trouvee; h = h.next, i++) chercher(h.memoizedState, 0);
    }
    if (trouvee !== S.carte) {                       // nouvelle carte (page rechargée) : les anciens repères ne servent plus
      S.sel = {}; S.tousMarq = {}; S.suivi = null;
      S.couchePas = null;
      if (trouvee) {
        trouvee.on("dragstart", () => { S.suivi = null; });
        trouvee.on("zoomend moveend", dessinerPas);       // les empreintes sont espacées en pixels : on les refait quand l'échelle ou la vue change
      }
    }
    S.carte = trouvee;
    return S.carte;
  }

  // ---------- Géométrie ----------
  function distance(a, b) {
    const p1 = (a[0] * Math.PI) / 180, p2 = (b[0] * Math.PI) / 180;
    const dp = p2 - p1, dl = ((b[1] - a[1]) * Math.PI) / 180;
    const h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
    return 2 * R_TERRE * Math.asin(Math.sqrt(h));
  }
  function cap(a, b) {
    const dlat = b[0] - a[0], dlon = (b[1] - a[1]) * Math.cos((((a[0] + b[0]) / 2) * Math.PI) / 180);
    return ((Math.atan2(dlon, dlat) * 180) / Math.PI + 360) % 360;
  }
  function temps(texte) { return new Date(String(texte).replace(" ", "T")).getTime(); }

  function preparer(e) {
    if (e._cumul) return e;
    e._cumul = [0];
    for (let i = 1; i < e.points.length; i++) e._cumul.push(e._cumul[i - 1] + distance(e.points[i - 1], e.points[i]));
    e._D = e._cumul[e._cumul.length - 1];
    if (e.t0 === undefined) { e.t0 = temps(e.depart); e.t1 = temps(e.arrivee); }   // les trains « tous » ont déjà des millisecondes
    return e;
  }

  /** Coordonnées (et cap du tronçon) à `d` mètres du départ le long du tracé. */
  function coordA(e, d) {
    const pts = e.points, cumul = e._cumul;
    if (pts.length < 2) return { lat: pts[0][0], lon: pts[0][1], cap: 0 };
    const cible = Math.min(Math.max(d, 0), e._D);
    let lo = 1, hi = cumul.length - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (cumul[mid] >= cible) hi = mid; else lo = mid + 1; }
    const seg = cumul[lo] - cumul[lo - 1], reste = seg > 0 ? (cible - cumul[lo - 1]) / seg : 0;
    const a = pts[lo - 1], b = pts[lo];
    return { lat: a[0] + (b[0] - a[0]) * reste, lon: a[1] + (b[1] - a[1]) * reste, cap: cap(a, b) };
  }
  /** Position à `d` mètres, avec un cap lissé : direction entre le point d'avant et celui d'après, pour des virages progressifs. */
  function pointA(e, d) {
    const p = coordA(e, d);
    const avant = coordA(e, d - LISSAGE_CAP_M), apres = coordA(e, d + LISSAGE_CAP_M);
    if (distance([avant.lat, avant.lon], [apres.lat, apres.lon]) > 5) p.cap = cap([avant.lat, avant.lon], [apres.lat, apres.lon]);
    return p;
  }

  // ---------- Mouvement : accélération, croisière, freinage ----------
  /** Profil d'un trajet entre deux arrêts : distance D (m) à parcourir en T (s) avec une accélération a (m/s²). */
  function profil(e) {
    if (e._prof) return e._prof;
    const D = e._D, T = Math.max((e.t1 - e.t0) / 1000, 1);
    let a = e.acc || 0.7;
    if (a * a * T * T < 4 * a * D) a = (4 * D) / (T * T);     // horaire trop serré pour cette accélération : on accélère plus fort (profil triangulaire)
    const vc = (a * T - Math.sqrt(Math.max(a * a * T * T - 4 * a * D, 0))) / 2;
    return (e._prof = { D, T, a, vc, ta: vc / a });
  }
  /** Où en est le train à l'instant tMs : distance parcourue s (m), vitesse v (m/s), reste (m), part du parcours f (0 à 1). */
  function etat(e, tMs) {
    const p = profil(e);
    const t = Math.min(Math.max((tMs - e.t0) / 1000, 0), p.T);
    let s, v;
    if (t < p.ta) { s = 0.5 * p.a * t * t; v = p.a * t; }
    else if (t > p.T - p.ta) { const u = p.T - t; s = p.D - 0.5 * p.a * u * u; v = p.a * u; }
    else { s = 0.5 * p.a * p.ta * p.ta + p.vc * (t - p.ta); v = p.vc; }
    return { s, v, reste: p.D - s, f: p.D > 0 ? s / p.D : 1 };
  }

  // ---------- Horloge ----------
  function maintenant() {
    if (S.horloge && S.horloge.mode === "sim") {
      const departs = S.etapes.filter((e) => !e.marche && e.t0).map((e) => e.t0);
      if (departs.length) return Math.min(...departs) + (Date.now() - S.horloge.t0_reel * 1000) * VITESSE_SIM;
    }
    return Date.now();
  }
  const heure = (ms) => new Date(ms).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });

  // ---------- Repères ----------
  function creerRepere(carte, e, clef, tous) {
    const sprite = e.sprite ? `<img class="tj-img" src="/sprite-train/${e.sprite}.png" alt="">` : "";
    const pastille = e.sprite ? "" : `<div class="tj-pastille" style="background:${e.style.couleur}"><i class="fa-solid fa-bus"></i></div>`;   // seulement pour un car
    const html = `<div class="tj">${sprite}${pastille}<div class="tj-cible"></div></div>`;     // tj-cible : zone de clic plus large que l'image
    const m = L.marker([e.points[0][0], e.points[0][1]], {
      icon: L.divIcon({ className: "train-js", html, iconSize: [0, 0] }), zIndexOffset: tous ? 500 : 1000, keyboard: false,
    }).addTo(carte);
    m.bindPopup("", { autoPan: false, closeButton: true, closeOnClick: false, autoClose: true, className: "popup-train" });
    m.on("click", () => suivre(clef, m));
    m.on("popupclose", () => { if (S.suivi === clef) S.suivi = null; });
    m._img = m.getElement().querySelector(".tj-img");
    return m;
  }

  function donneesDe(clef) {
    return clef.startsWith("sel:") ? S.etapes[+clef.slice(4)] : S.tousData[clef];
  }
  function repereDe(clef) {
    return clef.startsWith("sel:") ? S.sel[clef] : S.tousMarq[clef];
  }

  /** Clic sur un train : zoom dessus (sans trop zoomer), fenêtre d'informations, puis la caméra le suit. */
  function suivre(clef, marqueur) {
    const e = donneesDe(clef);
    if (!e) return;
    S.suivi = clef; S.perdu = null;
    const carte = S.carte;
    marqueur.setPopupContent(contenu(e, maintenant()));
    marqueur.openPopup();
    S.pauseSuivi = performance.now() + 900;          // pendant le zoom animé, la caméra ne tire pas dans l'autre sens
    carte.flyTo(marqueur.getLatLng(), Math.max(carte.getZoom(), ZOOM_SUIVI), { duration: 0.8 });
  }

  function contenu(e, t) {
    const arret = !!e._arret;
    const et = arret ? { v: 0, reste: 0, f: 1 } : etat(e, t);
    const kmh = Math.round(et.v * 3.6), reste = et.reste / 1000;
    const retard = e.retard_min ? `<div style="color:#c0392b"><b>Retard annoncé : ${e.retard_min} min</b></div>` : "<div>À l'heure</div>";
    const situation = arret
      ? `<div class="vitesse">À l'arrêt à ${e.vers || "la gare"}${e._repart ? " · repart à " + heure(e._repart) : ""}</div>`
      : `<div class="vitesse"><b>${kmh} km/h</b> · il reste ${reste.toFixed(reste < 10 ? 1 : 0)} km${e.vers ? " jusqu'à " + e.vers : ""}</div>`;
    return `<div class="infos-train"><div class="titre"><span class="puce" style="background:${e.style.couleur}"></span>${e.libelle}</div>`
      + `<div class="service">${e.style.libelle}</div>`
      + (e.de ? `<div>${e.de} → ${e.vers}</div>` : "")
      + `<div>Départ ${heure(e.t0)} · Arrivée ${heure(e.t1)}</div>${retard}`
      + situation
      + (e.sur_voie === false ? `<div class="astuce">Tracé approximatif : ligne droite entre les gares (pas de voie trouvée).</div>` : "")
      + `<div class="barre"><div style="width:${(et.f * 100).toFixed(1)}%;background:${e.style.couleur}"></div></div>`
      + `<div>${Math.round(et.f * 100)} % du parcours</div>`
      + `<div class="astuce">La caméra suit ce train. Faites glisser la carte pour arrêter.</div></div>`;
  }

  // Taille d'un repère à l'échelle de la carte : sa longueur réelle en mètres divisée par les mètres que représente un pixel.
  function afficher(m, e, pos, carte, tous) {
    m.setLatLng([pos.lat, pos.lon]);
    if (!m._img) return;                              // sans image de train (car) : la pastille reste
    const mpp = (156543.03392 * Math.cos((pos.lat * Math.PI) / 180)) / Math.pow(2, carte.getZoom());
    const reel = e.longueur_m / mpp;
    const l = Math.min(Math.max(reel, tous ? LONGUEUR_MIN_TOUS_PX : LONGUEUR_MIN_PX), LARGEUR_MAX_PX);
    const h = Math.max((l / e.rapport) * ETIREMENT, tous ? 1.5 : 4), deg = Math.round(pos.cap - 90);
    const d = m._derniere;
    if (d && Math.abs(d.l - l) < 0.4 && d.deg === deg) return;   // rien n'a changé à l'écran : on ne touche pas au DOM (il y a des milliers de trains)
    m._derniere = { l, deg };
    m._img.style.display = "block";
    m._img.style.width = l.toFixed(1) + "px";
    m._img.style.height = h.toFixed(1) + "px";
    m._img.style.transform = `rotate(${deg}deg)`;
  }

  function retirer(table, clef) {
    if (table[clef]) { table[clef].remove(); delete table[clef]; }
  }

  // ---------- Boucle d'animation ----------
  function image() {
    S.trame = requestAnimationFrame(image);
    const carte = trouverCarte();
    if (!carte) return;
    const t = maintenant();

    // 0. Trajet avec correspondance : la caméra passe d'un train au suivant quand il démarre
    if (S.suivi && S.suivi.startsWith("sel:")) {
      const i = +S.suivi.slice(4), e = S.etapes[i];
      if (e && t > e.t1) {
        const j = S.etapes.findIndex((x, k) => k > i && !x.marche && x.t0);
        if (j >= 0 && t >= S.etapes[j].t0) { S.suivi = "sel:" + j; S.ouvrir = "sel:" + j; }
      }
    }

    // 1. Trains du trajet choisi
    const vus = new Set();
    S.etapes.forEach((e, i) => {
      if (e.marche || !e.t0 || !e.t1) return;
      const clef = "sel:" + i;
      const enRoute = t >= e.t0 && t <= e.t1 && e.t1 > e.t0;
      const aQuai = !enRoute && S.suivi === clef && t > e.t1;       // arrivé : on le garde à quai tant qu'on le suit
      if (!enRoute && !aQuai) { retirer(S.sel, clef); return; }
      vus.add(clef);
      e._arret = aQuai;
      const pos = pointA(e, aQuai ? e._D : etat(e, t).s);
      if (!S.sel[clef]) S.sel[clef] = creerRepere(carte, e, clef, false);
      afficher(S.sel[clef], e, pos, carte, false);
      e._pos = pos;
      if (S.ouvrir === clef) { S.ouvrir = null; S.sel[clef].setPopupContent(contenu(e, t)); S.sel[clef].openPopup(); }
    });
    Object.keys(S.sel).forEach((clef) => { if (!vus.has(clef)) retirer(S.sel, clef); });

    // 2. Tous les trains du réseau (seuls ceux de l'écran sont dessinés : il y en a des milliers)
    if (S.toutesActives && performance.now() - S.dernierTous >= PAS_TOUS_MS) {
      S.dernierTous = performance.now();
      majTous(carte, t);
    } else if (!S.toutesActives && Object.keys(S.tousMarq).length) {
      Object.keys(S.tousMarq).forEach((k) => retirer(S.tousMarq, k));
    }

    // 3. Caméra : elle suit le train cliqué
    if (S.suivi) {
      const e = donneesDe(S.suivi), marq = repereDe(S.suivi);
      if (e && e._pos && marq) {
        S.perdu = null;
        if (performance.now() >= S.pauseSuivi) {
          // le train reste dans la partie de la carte que le panneau de recherche ne cache pas
          // (à droite du panneau de recherche, au-dessus du panneau des trajets quand il est ouvert)
          const panneau = document.getElementById("search-panel"), trajets = document.getElementById("panneau-resultats");
          const dx = panneau && carte.getSize().x > 700 ? (panneau.offsetWidth + 40) / 2 : 0;
          const dy = trajets && trajets.offsetParent !== null ? -(trajets.offsetHeight + 16) / 2 : 0;
          const cible = carte.getSize().divideBy(2).add([dx, dy]);
          const decalage = carte.latLngToContainerPoint([e._pos.lat, e._pos.lon]).subtract(cible);
          if (Math.abs(decalage.x) + Math.abs(decalage.y) > 0.5) carte.panBy(decalage, { animate: false });
        }
        if (marq.isPopupOpen() && performance.now() - S.dernierPopup >= PAS_POPUP_MS) {
          S.dernierPopup = performance.now();
          marq.setPopupContent(contenu(e, t));
        }
      } else {
        // le train n'est plus dans les données (liste rafraîchie, ou train qui n'est pas encore reparti) : on patiente avant de lâcher la caméra
        S.perdu = S.perdu || performance.now();
        if (performance.now() - S.perdu > PATIENCE_SUIVI_MS) { S.suivi = null; S.perdu = null; }
      }
    }
  }

  /** Un train « tous réseaux » : son segment en cours, ou à quai à la fin du précédent si le suivant n'est pas encore parti. */
  function segmentCourant(segs, t) {
    for (let i = 0; i < segs.length; i++) {
      const e = segs[i];
      if (t >= e.t0 && t <= e.t1 && e.t1 > e.t0) { e._arret = false; return e; }
      if (t > e.t1 && i + 1 < segs.length && t < segs[i + 1].t0) { e._arret = true; e._repart = segs[i + 1].t0; return e; }
    }
    return null;
  }

  function majTous(carte, t) {
    const zone = carte.getBounds().pad(0.15);
    const vus = new Set();
    for (const [id, segs] of S.circ) {
      const e = segmentCourant(segs, t);
      if (!e) continue;
      const clef = "tous:" + id;
      const pos = pointA(e, e._arret ? e._D : etat(e, t).s);
      e._pos = pos;
      S.tousData[clef] = e;
      if (S.suivi !== clef && !zone.contains([pos.lat, pos.lon])) continue;   // hors de l'écran : pas de repère
      vus.add(clef);
      if (!S.tousMarq[clef]) S.tousMarq[clef] = creerRepere(carte, e, clef, true);
      afficher(S.tousMarq[clef], e, pos, carte, true);
    }
    Object.keys(S.tousMarq).forEach((clef) => { if (!vus.has(clef) && S.suivi !== clef) retirer(S.tousMarq, clef); });
  }

  // ---------- Empreintes de pas (trajets à pied) ----------
  /** Une foulée (deux empreintes) tous les PAS_EMPREINTE_PX pixels le long de chaque trajet à pied, tournée dans le sens de la marche. */
  function dessinerPas() {
    const carte = S.carte;
    if (!carte) return;
    if (!S.couchePas) S.couchePas = L.layerGroup().addTo(carte);
    S.couchePas.clearLayers();
    const zoom = carte.getZoom(), zone = carte.getBounds().pad(0.3);
    for (const ligne of S.pas) {
      const pts = ligne.map((p) => carte.project(L.latLng(p[0], p[1]), zoom));
      let avant = PAS_EMPREINTE_PX / 2;
      for (let i = 0; i + 1 < pts.length; i++) {
        const dx = pts[i + 1].x - pts[i].x, dy = pts[i + 1].y - pts[i].y, long = Math.hypot(dx, dy);
        if (long === 0) continue;
        const angle = (Math.atan2(dy, dx) * 180) / Math.PI;             // 0 = vers l'est, sens horaire (l'écran a l'axe y vers le bas)
        for (let d = avant; d <= long; d += PAS_EMPREINTE_PX) {
          const ll = carte.unproject(L.point(pts[i].x + (dx * d) / long, pts[i].y + (dy * d) / long), zoom);
          if (!zone.contains(ll)) continue;
          L.marker(ll, {
            interactive: false, keyboard: false,
            icon: L.divIcon({ className: "pas-js", iconSize: [0, 0], html: `<i class="fa-solid fa-shoe-prints" style="transform:rotate(${(angle + ANGLE_EMPREINTE).toFixed(0)}deg)"></i>` }),
          }).addTo(S.couchePas);
        }
        avant = (avant - long) % PAS_EMPREINTE_PX;
        if (avant <= 0) avant += PAS_EMPREINTE_PX;
      }
    }
  }

  function demarrer() {
    if (!S.trame) S.trame = requestAnimationFrame(image);
  }

  // ---------- Fonctions appelées par Dash (clientside_callback) ----------
  window.dash_clientside = Object.assign(window.dash_clientside || {}, {
    trains: {
      /** Trajet choisi ou horloge changés : on repart de zéro. */
      configurer: function (etapes, horloge) {
        Object.keys(S.sel).forEach((k) => retirer(S.sel, k));
        if (S.suivi && S.suivi.startsWith("sel:")) S.suivi = null;
        S.etapes = (etapes || []).map(preparer);
        S.horloge = horloge || { mode: "reel" };
        demarrer();
        return Date.now();
      },
      /** Trajets à pied du résultat affiché (listes de points [lat, lon]) : dessinés en empreintes de pas. */
      configurerPas: function (lignes) {
        S.pas = lignes || [];
        dessinerPas();
        return Date.now();
      },
      /** Liste des trains du réseau reçue du serveur, ou bouton « tous les trains » (dés)activé. */
      configurerTous: function (donnees) {
        const actif = !!(donnees && donnees.actif);
        S.toutesActives = actif;
        const circ = new Map();
        for (const e of (donnees && donnees.trains) || []) {
          e.t0 = e.t0 * 1000; e.t1 = e.t1 * 1000;      // secondes → millisecondes
          preparer(e);
          if (!circ.has(e.id)) circ.set(e.id, []);
          circ.get(e.id).push(e);
        }
        circ.forEach((segs) => segs.sort((a, b) => a.t0 - b.t0));
        S.circ = circ;                                  // S.tousData garde les anciens segments jusqu'au prochain calcul : la caméra ne perd pas son train
        if (!actif) { Object.keys(S.tousMarq).forEach((k) => retirer(S.tousMarq, k)); S.tousData = {}; if (S.suivi && S.suivi.startsWith("tous:")) S.suivi = null; }
        demarrer();
        return Date.now();
      },
    },
  });
})();
