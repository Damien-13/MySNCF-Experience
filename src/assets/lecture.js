/*
 * Lecture de la page à voix haute et accès au clavier (onglets Itinéraire et Analyse). Dash charge ce fichier tout seul (dossier assets de src/).
 *
 * Le résumé à lire est écrit par le serveur (lib/lecture.py) dans une zone masquée de l'onglet (#lecture-itineraire ou #lecture-analyse) :
 * les lecteurs d'écran l'annoncent d'eux-mêmes (aria-live), et le bouton « Écouter » la lit avec la synthèse vocale du navigateur (aucun service extérieur).
 */
(function () {
  "use strict";
  const ZONES = { "tab-1": "lecture-itineraire", "tab-2": "lecture-analyse" };

  const bouton = () => document.getElementById("btn-ecouter");
  const synthese = () => ("speechSynthesis" in window ? window.speechSynthesis : null);

  /** Le bouton montre si la lecture est en cours : « Arrêter » pendant la lecture, « Écouter » sinon. */
  function majBouton(enCours) {
    const b = bouton();
    if (!b) return;
    b.setAttribute("aria-pressed", enCours ? "true" : "false");
    const texte = b.querySelector(".texte-ecouter"), icone = b.querySelector("i");
    if (texte) texte.textContent = enCours ? "Arrêter" : "Écouter";
    if (icone) icone.className = `fa-solid ${enCours ? "fa-stop" : "fa-volume-high"} me-2`;
  }

  function voixFrancaise() {
    const voix = synthese().getVoices();
    return voix.find((v) => v.lang === "fr-FR") || voix.find((v) => v.lang && v.lang.toLowerCase().startsWith("fr")) || null;
  }

  function arreter() {
    const s = synthese();
    if (s && (s.speaking || s.pending)) s.cancel();
    majBouton(false);
  }

  // Un nouveau résumé (autre recherche, autre option) rend la lecture en cours obsolète : on l'arrête.
  const surveilles = new Set();
  function surveiller(zone) {
    if (!zone || surveilles.has(zone.id)) return;
    surveilles.add(zone.id);
    new MutationObserver(arreter).observe(zone, { childList: true, characterData: true, subtree: true });
  }

  // Un bloc d'option est un <div role="button"> : Entrée et Espace doivent le déclencher comme un clic (sinon il est inutilisable au clavier).
  document.addEventListener("keydown", (e) => {
    const cible = e.target;
    if ((e.key === "Enter" || e.key === " ") && cible && cible.getAttribute && cible.getAttribute("role") === "button" && cible.tagName === "DIV") {
      e.preventDefault();
      cible.click();
    }
  });

  window.dash_clientside = Object.assign(window.dash_clientside || {}, {
    lecture: {
      /** Clic sur « Écouter » : lit le résumé de l'onglet ouvert, ou arrête la lecture si elle est en cours. */
      ecouter: function (clics, onglet) {
        const s = synthese(), zone = document.getElementById(ZONES[onglet]);
        if (!s) {
          if (zone) zone.textContent = "La lecture à voix haute n'est pas disponible dans ce navigateur.";
          const b = bouton();
          if (b) b.disabled = true;
          return Date.now();
        }
        if (s.speaking || s.pending) { arreter(); return Date.now(); }
        const texte = zone ? zone.textContent.trim() : "";
        if (!texte) return Date.now();
        surveiller(zone);
        const lecture = new SpeechSynthesisUtterance(texte);
        lecture.lang = "fr-FR";
        const voix = voixFrancaise();
        if (voix) lecture.voice = voix;
        lecture.onend = lecture.onerror = () => majBouton(false);
        s.cancel();
        s.speak(lecture);
        majBouton(true);
        return Date.now();
      },
      /** Changement d'onglet : le résumé lu n'est plus celui de la page affichée. */
      arreter: function (onglet) {
        arreter();
        return Date.now();
      },
    },
  });
})();
