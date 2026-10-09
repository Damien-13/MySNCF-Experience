/*
 * Animation des trains sur la carte (onglet Itinéraire voyageur). Dash charge ce fichier tout seul (dossier assets de src/).
 *
 * Pourquoi côté navigateur : le serveur ne peut renvoyer une position qu'une fois par seconde, ce qui donne un mouvement saccadé.
 * Ici, chaque image de l'écran (60 par seconde) recalcule la position du train à partir des horaires reçus.
 *
 * Données (envoyées par src/app.py, voir lib/suivi.py pour le même calcul côté serveur) :
 *   etapes : un objet par étape du trajet choisi : points [[lat, lon], …], depart / arrivee (« AAAA-MM-JJ HH:MM:SS »), retard_min, libelle,
 *            de / vers (gares), marche, style {couleur, libelle}, sprite (image du train ou null), longueur_m, rapport.
 *   tous   : les trains en circulation sur tout le réseau (même forme, depart / arrivee en secondes depuis l'époque).
 *   horloge : {mode: "reel"} ou {mode: "sim", t0_reel: secondes} (le trajet défile à VITESSE_SIM fois la vitesse réelle).
 *
 * Taille : un train fait sa longueur réelle (100 à 200 m) à l'échelle de la carte, donc il grandit en zoomant et reste minuscule en dézoomant.
 * Trop petit pour qu'on le reconnaisse (moins de SEUIL_IMAGE_PX), il devient une pastille.
 * Clic sur un train : fenêtre d'informations, et la caméra le suit jusqu'à la fermeture de la fenêtre ou un déplacement de la carte à la main.
 */
(function () {
  const VITESSE_SIM = 120;           // 1 seconde réelle = 2 minutes de trajet, comme lib/suivi.py
  const SEUIL_IMAGE_PX = 24;         // en dessous, pastille au lieu de l'image du train
  const LARGEUR_MAX_PX = 700;
  const ETIREMENT = 1.8;             // les trains vus du dessus sont très fins : on les élargit un peu pour qu'on les reconnaisse
  const PAS_TOUS_MS = 200;           // les trains « tous réseaux » sont recalculés 5 fois par seconde (il y en a des milliers)
  const R_TERRE = 6371008.8;

  const S = (window.__trains = window.__trains || {
    carte: null, etapes: [], horloge: { mode: "reel" }, tous: [], toutesActives: false,
    sel: {}, tousMarq: {}, suivi: null, trame: null, dernierTous: 0, rendu: null,
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
      S.sel = {}; S.tousMarq = {}; S.suivi = null; S.rendu = null;
      if (trouvee) trouvee.on("dragstart", () => { S.suivi = null; });
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
    if (e.t0 === undefined) { e.t0 = temps(e.depart); e.t1 = temps(e.arrivee); }   // les trains « tous » ont déjà des millisecondes
    return e;
  }
  function pointA(e, f) {
    const pts = e.points, cumul = e._cumul;
    if (pts.length < 2) return { lat: pts[0][0], lon: pts[0][1], cap: 0 };
    const cible = Math.min(Math.max(f, 0), 1) * cumul[cumul.length - 1];
    let lo = 1, hi = cumul.length - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (cumul[mid] >= cible) hi = mid; else lo = mid + 1; }
    const seg = cumul[lo] - cumul[lo - 1], reste = seg > 0 ? (cible - cumul[lo - 1]) / seg : 0;
    const a = pts[lo - 1], b = pts[lo];
    return { lat: a[0] + (b[0] - a[0]) * reste, lon: a[1] + (b[1] - a[1]) * reste, cap: cap(a, b) };
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
    const sprite = e.sprite
      ? `<img class="tj-img" src="/sprite-train/${e.sprite}.png" alt="">`
      : "";
    const icone = e.sprite ? "fa-train" : "fa-bus";
    const html = `<div class="tj">${sprite}<div class="tj-pastille" style="background:${e.style.couleur}"><i class="fa-solid ${icone}"></i></div></div>`;
    const m = L.marker([e.points[0][0], e.points[0][1]], {
      icon: L.divIcon({ className: "train-js", html, iconSize: [0, 0] }), zIndexOffset: tous ? 500 : 1000, keyboard: false,
    }).addTo(carte);
    m.bindPopup("", { autoPan: false, closeButton: true, className: "popup-train" });
    m.on("click", () => suivre(clef, m, e));
    m.on("popupclose", () => { if (S.suivi === clef) S.suivi = null; });
    m._img = m.getElement().querySelector(".tj-img");
    m._pastille = m.getElement().querySelector(".tj-pastille");
    return m;
  }

  function suivre(clef, marqueur, e) {
    S.suivi = clef;
    const carte = S.carte;
    if (carte.getZoom() < 9) carte.setZoom(9, { animate: false });
    marqueur.setPopupContent(contenu(e, maintenant()));
    marqueur.openPopup();
  }

  function contenu(e, t) {
    const f = Math.min(Math.max((t - e.t0) / (e.t1 - e.t0), 0), 1);
    const km = e._cumul[e._cumul.length - 1] / 1000, heures = (e.t1 - e.t0) / 3600000;
    const retard = e.retard_min ? `<div style="color:#c0392b"><b>Retard annoncé : ${e.retard_min} min</b></div>` : "<div>À l'heure</div>";
    return `<div class="infos-train"><div class="titre"><span class="puce" style="background:${e.style.couleur}"></span>${e.libelle}</div>`
      + `<div class="service">${e.style.libelle}</div>`
      + (e.de ? `<div>${e.de} → ${e.vers}</div>` : "")
      + `<div>Départ ${heure(e.t0)} · Arrivée ${heure(e.t1)}</div>${retard}`
      + `<div class="barre"><div style="width:${(f * 100).toFixed(1)}%;background:${e.style.couleur}"></div></div>`
      + `<div>${Math.round(f * 100)} % du parcours · ${km.toFixed(0)} km`
      + (heures > 0 ? ` · ${Math.round(km / heures)} km/h de moyenne` : "") + `</div><div class="astuce">La caméra suit ce train.</div></div>`;
  }

  // Taille d'un repère à l'échelle de la carte : sa longueur réelle en mètres divisée par les mètres que représente un pixel.
  function afficher(m, e, pos, carte) {
    m.setLatLng([pos.lat, pos.lon]);
    const mpp = (156543.03392 * Math.cos((pos.lat * Math.PI) / 180)) / Math.pow(2, carte.getZoom());
    const px = e.longueur_m / mpp;
    if (m._img && px >= SEUIL_IMAGE_PX) {
      const l = Math.min(px, LARGEUR_MAX_PX), h = Math.max((l / e.rapport) * ETIREMENT, 4);
      m._img.style.display = "block";
      m._img.style.width = l.toFixed(1) + "px";
      m._img.style.height = h.toFixed(1) + "px";
      m._img.style.transform = `rotate(${(pos.cap - 90).toFixed(1)}deg)`;
      m._pastille.style.display = "none";
    } else {
      if (m._img) m._img.style.display = "none";
      m._pastille.style.display = "flex";
    }
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

    // 1. Trains du trajet choisi
    const vus = new Set();
    S.etapes.forEach((e, i) => {
      if (e.marche || !e.t0 || !e.t1) return;
      const clef = "sel:" + i;
      if (t < e.t0 || t > e.t1 || e.t1 <= e.t0) { retirer(S.sel, clef); return; }
      vus.add(clef);
      const pos = pointA(e, (t - e.t0) / (e.t1 - e.t0));
      if (!S.sel[clef]) S.sel[clef] = creerRepere(carte, e, clef, false);
      afficher(S.sel[clef], e, pos, carte);
      e._pos = pos;
    });
    Object.keys(S.sel).forEach((clef) => { if (!vus.has(clef)) retirer(S.sel, clef); });

    // 2. Tous les trains du réseau (points seulement : il y en a des milliers)
    if (S.toutesActives && performance.now() - S.dernierTous >= PAS_TOUS_MS) {
      S.dernierTous = performance.now();
      majTous(carte, t);
    } else if (!S.toutesActives && Object.keys(S.tousMarq).length) {
      Object.keys(S.tousMarq).forEach((k) => retirer(S.tousMarq, k));
    }

    // 3. Caméra : elle suit le train cliqué
    if (S.suivi) {
      const e = S.suivi.startsWith("sel:") ? S.etapes[+S.suivi.slice(4)] : S.tousData && S.tousData[S.suivi];
      const marq = S.suivi.startsWith("sel:") ? S.sel[S.suivi] : S.tousMarq[S.suivi];
      if (e && e._pos && marq) {
        // le train reste dans la partie de la carte que le panneau de recherche ne cache pas
        const panneau = document.getElementById("search-panel");
        const cible = carte.getSize().divideBy(2).add([panneau && carte.getSize().x > 700 ? (panneau.offsetWidth + 40) / 2 : 0, 0]);
        const decalage = carte.latLngToContainerPoint([e._pos.lat, e._pos.lon]).subtract(cible);
        if (Math.abs(decalage.x) + Math.abs(decalage.y) > 0.5) carte.panBy(decalage, { animate: false });
        if (marq.isPopupOpen()) marq.setPopupContent(contenu(e, t));
      } else {
        S.suivi = null;
      }
    }
  }

  function majTous(carte, t) {
    const zone = carte.getBounds().pad(0.15);
    S.tousData = S.tousData || {};
    const vus = new Set();
    for (const e of S.tous) {
      preparer(e);
      if (t < e.t0 || t > e.t1 || e.t1 <= e.t0) continue;
      const pos = pointA(e, (t - e.t0) / (e.t1 - e.t0));
      e._pos = pos;
      const clef = "tous:" + e.id;
      S.tousData[clef] = e;
      if (S.suivi !== clef && !zone.contains([pos.lat, pos.lon])) continue;   // hors de l'écran : pas de repère
      vus.add(clef);
      if (!S.tousMarq[clef]) {
        const m = L.circleMarker([pos.lat, pos.lon], { radius: 4, color: "#ffffff", weight: 1, fillColor: e.style.couleur, fillOpacity: 0.95, renderer: S.canvas || (S.canvas = L.canvas({ padding: 0.3 })) }).addTo(carte);
        m.bindPopup("", { autoPan: false, className: "popup-train" });
        m.on("click", () => { S.suivi = clef; carte.getZoom() < 9 && carte.setZoom(9, { animate: false }); m.setPopupContent(contenu(e, maintenant())); m.openPopup(); });
        m.on("popupclose", () => { if (S.suivi === clef) S.suivi = null; });
        S.tousMarq[clef] = m;
      }
      S.tousMarq[clef].setLatLng([pos.lat, pos.lon]);
      S.tousMarq[clef].setRadius(carte.getZoom() >= 11 ? 6 : carte.getZoom() >= 8 ? 4.5 : 3.5);
    }
    Object.keys(S.tousMarq).forEach((clef) => { if (!vus.has(clef)) retirer(S.tousMarq, clef); });
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
      /** Liste des trains du réseau reçue du serveur, ou bouton « tous les trains » (dés)activé. */
      configurerTous: function (donnees) {
        const actif = !!(donnees && donnees.actif);
        S.toutesActives = actif;
        S.tous = ((donnees && donnees.trains) || []).map((e) => {
          e.t0 = e.t0 * 1000; e.t1 = e.t1 * 1000;      // secondes → millisecondes
          return e;
        });
        S.tousData = {};
        if (!actif) { Object.keys(S.tousMarq).forEach((k) => retirer(S.tousMarq, k)); if (S.suivi && S.suivi.startsWith("tous:")) S.suivi = null; }
        demarrer();
        return Date.now();
      },
    },
  });
})();
