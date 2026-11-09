/* v39: the third register (docs/DEFECTS.md), the friction trade market in the trade screen, contract talks with
   clauses and pitches, professional tryouts, and a French (Quebec) interface option. Loads last; boots the app. */

/* ================================================================ #12 console output in a window */
function consoleOut(text, err = false) {
  let w = $("#con-out");
  if (!w) {
    document.body.insertAdjacentHTML("beforeend", `<div id="con-out" class="con-out"><header>Console<button title="Close" aria-label="Close">×</button></header><pre></pre></div>`);
    w = $("#con-out");
    w.querySelector("button").onclick = () => w.remove();
  }
  w.classList.toggle("err", !!err);
  w.querySelector("pre").textContent = text.trim();
}

/* ================================================================ #13 search, #14 credits once, #15 credits text */
const Search = {
  open() {
    Modal.open(`<div class="win-title">Search</div><div class="pad"><input id="sx-q" class="wide" placeholder="Player, club or staff name" autocomplete="off" style="width:100%">
      <div id="sx-res" class="sx-res" style="margin-top:8px;max-height:50vh;overflow:auto"></div></div>
      <div class="win-buttons"><button onclick="Modal.close()">Close</button></div>`, "win");
    const q = $("#sx-q"); let t = null;
    q.focus();
    q.oninput = () => {
      clearTimeout(t);
      const s = q.value.trim();
      if (s.length < 2) { $("#sx-res").innerHTML = ""; return; }
      t = setTimeout(async () => {
        const d = await api("search", {q: s}).catch(() => ({players: [], teams: []}));
        $("#sx-res").innerHTML = (d.teams.map((x) => `<div><a href="#team/${x.team_id}" onclick="Modal.close()">${crest(x.abbr, 14)} ${esc(x.name)}</a></div>`).join("")
          + d.players.map((p) => `<div><a href="#player/${p.player_id}" onclick="Modal.close()"><span class="pos">${esc(p.pos)}</span> ${esc(p.name)}</a> <span class="muted">${esc(p.team || p.status || "")}</span></div>`).join("")
          + (d.staff || []).map((x) => `<div><a href="#staffer/${x.staff_id}" onclick="Modal.close()">${esc(x.name)}</a> <span class="muted">${esc(x.role || "")} ${esc(x.team || "")}</span></div>`).join(""))
          || '<p class="muted">Nobody by that name.</p>';
      }, 160);
    };
  },
};
(function fixMenus() {
  const help = MENUS.find((m) => m[0] === "Help");
  if (help && !help[1].some((x) => Array.isArray(x) && x[0] === "Report a bug")) help[1].push(["Report a bug", () => BugReport.open()]);
  const file = MENUS[0][1];
  const ci = file.findIndex((x) => Array.isArray(x) && x[0] === "Credits");
  if (ci >= 0) file.splice(ci, 1);                                  // #14: Credits lives under Help only
  const mgr = MENUS[1][1];
  const si = mgr.findIndex((x) => Array.isArray(x) && x[0] === "Search...");
  if (si >= 0) mgr[si] = ["Search...", () => Search.open(), null, "Ctrl+F"];   // #13: a search window that works
})();
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "f" && STATE && STATE.loaded) { e.preventDefault(); Search.open(); }
});

const creditsV39 = Credits.open.bind(Credits);
Credits.open = function (about = false) {
  if (about) return creditsV39(true);
  Modal.open(`<div class="win-title">Credits</div>
    <div class="credits">
      <div class="cr-logo">HOCKEY <span>MANAGER</span><i>version ${esc(APP.version || "")}</i></div>
      <h4>Design / Architecture / Lead developer</h4><p>Jeremy Legere</p>
      <h4>Quality assurance / Testing / Code review</h4><p>Jeremy Legere</p>
      <h4>AI collaboration and engineering assistance</h4><ul>
        <li><b>Claude</b> (Anthropic): primary code generation and development</li>
        <li><b>Gemini</b> (Google): 2D Python simulation engine architecture, simulation mathematics, AI trade logic, free agency and algorithmic design</li>
        <li><b>ChatGPT</b> (OpenAI): SQLite database structuring and schema architecture</li></ul>
      <p class="small muted">AI tools were used under the lead developer's direction; every design decision, review and test is his. Generated code is reviewed and tested before it ships, and no personal or confidential data is given to the tools.</p>
      <h4>Inspired by</h4><p>The classic hockey management games of the early 2000s, reimagined with modern mechanics. No code, data, art or text from any of them is used.</p>
      <h4>Built with</h4><ul>
        <li>Python and SQLite (the core game, the save files)</li>
        <li>plotly.js 2.35 (analytics charts; MIT licence)</li>
        <li>pywebview (the desktop window; BSD licence), with WebView2, WebKit or Qt WebEngine underneath</li></ul>
      <h4>Data</h4><p>The world that ships with the game is fictional: every club, town and player is invented, so nothing in it is anyone's mark or likeness. Build your own league from a spreadsheet (docs/BUILD_YOUR_OWN.md), edit any player or club in the editor, or import your own export of a community database for personal use (File &gt; Import Database). Club crests and player portraits are drawn by the game.</p>
      <h4>Names</h4><p>If you load real league, club or player names from your own data, that stays on your computer: it is for your personal use and must not be shared or published.</p>
      <h4>Found a bug?</h4><p>Help &gt; Report a bug, or write to <a href="mailto:jeremy.legere@gmail.com?subject=Hockey%20Manager%20bug%20report">jeremy.legere@gmail.com</a>.</p>
      <p class="muted small">A personal, open-source project. Thanks for playing.</p>
    </div>
    <div class="win-buttons"><button class="primary" onclick="Modal.close()">Close</button></div>`, "win");
};

/* ================================================================ #7 contract talks: trade protection and pitches */
Talks.clause = "none";
const talksRenderV39 = Talks.render.bind(Talks);
Talks.render = function (v) {
  if (v && v.open && v.clause_asks) {
    if (!(this.clause in v.clause_asks)) this.clause = "none";
    v = Object.assign({}, v, {asks: v.clause_asks[this.clause], wants_ntc: false});
  }
  talksRenderV39(v);
  if (!v || !v.open || !v.clause_asks) return;
  const row = document.querySelector(".tk-offer .row");
  if (row && v.age >= 26) {
    const opts = Object.keys(v.clause_asks).map((k) => `<option value="${k}"${k === this.clause ? " selected" : ""}>${esc(v.clause_text[k])}</option>`).join("");
    row.insertAdjacentHTML("afterend", `<div class="tk-clause"><label>Trade protection <select id="tk-clause">${opts}</select></label>
      ${v.wants_level ? `<span class="muted small">he wants ${esc(["", "a no-trade list", "a full no-trade clause", "a no-movement clause"][v.wants_level] || "protection")}: each level you give up to that takes 2.5% off; each level short costs 2%</span>` : '<span class="muted small">he is not asking for any</span>'}</div>`);
    $("#tk-clause").onchange = (e) => { this.clause = e.target.value; this.render(v._raw || v); };
  }
  const wants = document.querySelector(".tk-wants");
  if (wants && v.pitches) {
    wants.insertAdjacentHTML("beforeend", `<h4>Make your pitch</h4><div class="tk-pitch">${v.pitches.map((p) =>
      `<button data-pitch="${p.key}"${p.used ? " disabled" : ""}>${esc(p.label)}</button>`).join("")}</div>`);
    wants.querySelectorAll("[data-pitch]").forEach((b) => b.onclick = async () => {
      const r = await quietCmd(`pitch ${this.pid} ${b.dataset.pitch}`);
      if (!r.ok) toast(r.output, true);
      this.render(await api("negotiation", {id: this.pid}));
    });
  }
};
Talks.send = async function () {
  const box = $("#tk-log");
  const prot = this.clause && this.clause !== "none" ? this.clause : "";
  box.insertAdjacentHTML("beforeend", `<div class="bub you"><div class="who">You</div>${this.years} yr x ${mil(this.aav)}${prot ? " with trade protection" : ""}</div><div class="bub agent typing"><i></i><i></i><i></i></div>`);
  box.scrollTop = box.scrollHeight;
  document.querySelectorAll(".tk-offer button").forEach((b) => b.disabled = true);
  const r = await quietCmd(`propose ${this.pid} ${Math.round(this.aav)} ${this.years}${prot ? " " + prot : ""}`);
  await new Promise((res) => setTimeout(res, 650));
  if (!r.ok) toast(r.output, true);
  this.render(await api("negotiation", {id: this.pid}));
};

/* ================================================================ #5 the trade screen: picks by year and round, protection, clauses */
const tradeV39 = VIEWS.trade;
VIEWS.trade = async (team) => {
  const html = await tradeV39(team);
  const d = await api("trade", team ? {team} : {});
  const byKey = {};
  [["give", d.mine], ["get", d.theirs]].forEach(([side, as]) => { if (as) as.picks.forEach((p) => (byKey[side + "|" + p.key] = p)); });
  const pinfo = {};
  [d.mine, d.theirs].forEach((as) => as && as.players.forEach((p) => (pinfo[p.key] = p)));
  const prev = AFTER;
  AFTER = () => {
    if (prev) prev();
    // players: clause and friction tags
    document.querySelectorAll('.tr-a[value^="player:"]').forEach((x) => {
      const p = pinfo[x.value];
      const cell = x.closest("tr") && x.closest("tr").children[1];
      if (!p || !cell) return;
      if (p.clause) cell.insertAdjacentHTML("beforeend", ` <span class="tag clause" title="Trade protection: he must agree to a trade, or a list of clubs is off limits">${esc(p.clause)}</span>`);
      if (p.friction != null && p.friction >= 20) cell.insertAdjacentHTML("beforeend", ` <span class="tag fr" title="How hard he is to pry loose (0-100): they want 1.05 + this/100 of his value, and they only shop him to clubs whose need is at least this">hard to get ${p.friction}</span>`);
    });
    // picks: a grid by year and round instead of a run of chips
    document.querySelectorAll(".picks").forEach((box) => {
      const inputs = [...box.querySelectorAll("input.tr-a")];
      if (!inputs.length) return;
      const side = inputs[0].dataset.side;
      const years = {};
      inputs.forEach((x) => { const [, y, r] = x.value.split(":"); ((years[y] = years[y] || {})[r] = years[y][r] || []).push(x); });
      const rounds = [1, 2, 3, 4, 5, 6, 7];
      const rows = Object.keys(years).sort().map((y) => `<tr><td class="yr">${y}</td>${rounds.map((r) => `<td>${(years[y][r] || []).map((x) => {
        const p = byKey[side + "|" + x.value] || {};
        const prot = side === "give" && r === 1 && p.protect_values ? `<select class="tp-prot" data-for="${x.value}" title="Protect it: if it lands in the top N it stays with you and next year's 1st goes instead">
          <option value="">no prot.</option>${[3, 5, 10].map((t) => `<option value="${t}">top-${t}</option>`).join("")}</select>` : "";
        return `<label class="tp-pk" title="${esc(p.label || "")}"><input type="checkbox" class="tr-a" data-side="${side}" value="${x.value}" data-name="${esc(x.dataset.name)}" data-pos="pick" data-cap="0" data-val="${x.dataset.val}"${x.checked ? " checked" : ""}>
          ${p.own === false ? `<span class="from">${esc(p.orig)}</span> ` : ""}<span class="v">${x.dataset.val}</span></label>${prot}`;
      }).join("") || '<span class="muted">-</span>'}</td>`).join("")}</tr>`).join("");
      box.innerHTML = `<div class="tp-wrap"><table class="tp-picks nosort"><tr><th></th>${rounds.map((r) => `<th>R${r}</th>`).join("")}</tr>${rows}</table></div>
        <p class="muted small">Pick values follow the standings (this year) or regress to mid-round (later years). ${side === "give" ? "A 1st can be protected: top 3, 5 or 10." : ""}</p>`;
    });
    document.querySelectorAll(".tp-prot").forEach((s) => s.onchange = () => {
      const base = s.dataset.for;
      const box = s.previousElementSibling.querySelector("input");
      const p = byKey["give|" + base] || {};
      box.value = s.value ? `${base}:p${s.value}` : base;
      box.dataset.name = (p.label || box.dataset.name).replace(/ \(top-\d+ protected\)$/, "") + (s.value ? ` (top-${s.value} protected)` : "");
      box.dataset.val = s.value && p.protect_values ? String(Math.round(p.protect_values[s.value])) : String(Math.round(p.value || 0));
      s.previousElementSibling.querySelector(".v").textContent = box.dataset.val;
      if (!box.checked) box.checked = true;
      box.dispatchEvent(new Event("change", {bubbles: true}));
    });
    // re-attach the verdict to the rebuilt checkboxes
    const any = document.querySelector(".tr-a");
    if (any) document.querySelectorAll(".tp-pk .tr-a").forEach((x) => x.addEventListener("change", () => {
      const other = document.querySelector('.tr-a[value^="player:"]');
      if (other) { other.dispatchEvent(new Event("change", {bubbles: true})); }
    }));
    // their needs, in words
    if (d.needs) {
      const ev = $("#tr-eval");
      if (ev) ev.insertAdjacentHTML("beforebegin", `<p class="small">Their needs (0-100): forwards <b>${d.needs.F}</b> · defence <b>${d.needs.D}</b> · goal <b>${d.needs.G}</b>
        <span class="muted">· competitive state ${Math.round(d.state * 100)}/100. A club pursues a player only when its need there is at least his "hard to get" score.</span></p>`);
    }
  };
  return html;
};

/* ================================================================ #16 French (Quebec) interface */
// The interface chrome (menus, tabs, buttons, headings, common labels) in Quebec French. Text the game writes (news,
// messages, press questions, recaps) stays in English for now (docs/DEFECTS.md #16).
const FR = {
  // menus
  "File": "Fichier", "Manager": "Directeur", "Team": "Équipe", "League": "Ligue", "Statistics": "Statistiques", "Play": "Jouer", "Help": "Aide",
  "New Game...": "Nouvelle partie...", "Load Game...": "Charger une partie...", "Save Game As...": "Enregistrer sous...", "Import Database...": "Importer une base de données...",
  "Backups...": "Copies de sécurité...", "Settings...": "Réglages...", "Console": "Console", "Start Screen": "Écran d'accueil", "Exit": "Quitter",
  "Office": "Bureau", "Inbox": "Boîte de réception", "Press Room": "Salle de presse", "Job Security": "Sécurité d'emploi", "Manager Profile": "Profil du DG",
  "Assistant GM": "DG adjoint", "Notes": "Notes", "Short List": "Liste de surveillance", "Achievements": "Accomplissements", "Job Centre": "Centre d'emploi",
  "Find Players...": "Trouver des joueurs...", "Search...": "Rechercher...", "Search": "Rechercher",
  "Roster": "Alignement", "Lineup and Tactics": "Trios et tactiques", "Leadership Group...": "Groupe de leaders...", "Contracts and Cap": "Contrats et plafond",
  "Prospects": "Espoirs", "Development": "Développement", "Staff": "Personnel", "Scouting": "Dépistage", "Trade Offer": "Proposition d'échange",
  "Three-Team Trade": "Échange à trois", "Calendar": "Calendrier", "Schedule and Results": "Calendrier et résultats", "Team Page": "Page de l'équipe",
  "Organisation History": "Histoire de l'organisation", "Standings": "Classement", "Playoffs": "Séries éliminatoires", "Free Agent Centre": "Centre des joueurs autonomes",
  "Transactions": "Transactions", "Re-signing (Rights)": "Renouvellements (droits)", "Free Agency War Room": "Salle de guerre (joueurs autonomes)",
  "Draft Room": "Salle du repêchage", "News": "Nouvelles", "League Trades": "Échanges de la ligue", "League History": "Histoire de la ligue",
  "League Leaders": "Meneurs de la ligue", "Player Statistics": "Statistiques des joueurs", "Goalie Statistics": "Statistiques des gardiens",
  "Team Statistics": "Statistiques des équipes", "Advanced Analytics": "Analytique avancée", "Playoff Odds": "Chances de séries", "Records and Awards": "Records et trophées",
  "Continue (one day)": "Continuer (un jour)", "One Week": "Une semaine", "To Next Game": "Jusqu'au prochain match", "Rest of Season": "Reste de la saison",
  "Next Offseason Phase": "Prochaine étape de l'entre-saison", "Credits": "Générique", "About": "À propos", "Champions": "Champions", "Awards Night": "Soirée des trophées",
  // tabs and bars
  "Lineup": "Trios", "Contracts": "Contrats", "Name": "Nom", "Short list": "Liste de surveillance", "Nobody on waivers.": "Personne au ballottage.", "Trade": "Échanges", "Back": "Retour", "Forward": "Avancer", "Day": "Jour", "Week": "Semaine",
  "Continue to next game": "Continuer au prochain match", "Continue one day": "Continuer un jour", "Rest of season": "Reste de la saison", "Saves": "Parties",
  "Press room": "Salle de presse", "Watch": "Regarder", "Normal": "Normal", "Fast": "Rapide", "Instant": "Instantané", "STOP": "ARRÊT", "CLOSE": "FERMER",
  "SIM CENTRE": "CENTRE DE SIMULATION", "Scores": "Pointages", "Your club": "Votre club", "Goal leaders": "Meneurs des buteurs",
  // common buttons
  "Close": "Fermer", "Cancel": "Annuler", "OK": "OK", "Save": "Enregistrer", "Save lines": "Enregistrer les trios", "Automatic": "Automatique",
  "Tactics": "Tactiques", "Propose": "Proposer", "Clear": "Effacer", "What would it take?": "Qu'est-ce que ça prendrait?", "Accept": "Accepter",
  "Decline": "Refuser", "Block": "Bloc", "Unblock": "Retirer du bloc", "Send down": "Rétrograder", "Recall": "Rappeler", "Swap": "Échanger",
  "Talk extension": "Discuter prolongation", "Negotiate": "Négocier", "Negotiate extension": "Négocier une prolongation", "Make offer": "Faire une offre",
  "Offer his ask": "Offrir sa demande", "Walk away": "Mettre fin", "Mark read": "Marquer comme lu", "Mark unread": "Marquer comme non lu",
  "Flag": "Signaler", "Archive": "Archiver", "Mark all read": "Tout marquer comme lu", "Sign at his asking price": "Signer à son prix",
  "Invite to camp (tryout)": "Inviter au camp (essai)", "Full recap & replay": "Résumé complet et reprise", "Recaps": "Résumés", "Schedule": "Calendrier",
  // headings and labels
  "Forwards": "Attaquants", "Defence": "Défense", "Goal": "Gardiens", "Power play": "Avantage numérique", "Penalty kill": "Désavantage numérique",
  "Overtime units": "Unités de prolongation", "Roles and tendencies": "Rôles et tendances", "Player types and tendencies": "Types de joueurs et tendances", "Player": "Joueur", "Pos": "Pos", "Age": "Âge", "Cap hit": "Impact sur le plafond",
  "Value": "Valeur", "Morale": "Moral", "Status": "Statut", "Waivers": "Ballottage", "Final season": "Dernière saison", "Starter": "Partant", "Backup": "Auxiliaire",
  "The proposal": "La proposition", "Their view": "Leur point de vue", "Offers to you": "Offres reçues", "Waiver wire": "Liste de ballottage",
  "Whole organisation": "Toute l'organisation", "Depth chart": "Tableau de profondeur", "Draft rights": "Droits de repêchage", "Injured": "Blessés",
  "NHL roster": "Alignement de la LNH", "Suggestions": "Suggestions", "Favourites": "Favoris", "Folders": "Dossiers", "Unread": "Non lus", "Flagged": "Signalés",
  "Owner & board": "Propriétaire et conseil", "Players & agents": "Joueurs et agents", "Trades": "Échanges", "Staff reports": "Rapports du personnel",
  "League office": "Bureau de la ligue", "Today": "Aujourd'hui", "Yesterday": "Hier", "Last week": "La semaine dernière", "Earlier this week": "Plus tôt cette semaine",
  "Earlier this month": "Plus tôt ce mois-ci", "Older": "Plus ancien", "Select a message to read it.": "Choisissez un message pour le lire.",
  "Three stars": "Trois étoiles", "Score by period": "Pointage par période", "Play by play": "Jeu par jeu", "Speed": "Vitesse", "Pause": "Pause",
  "Eastern Conference": "Association de l'Est", "Western Conference": "Association de l'Ouest", "Wild card": "Meilleurs deuxièmes", "Metropolitan": "Métropolitaine",
  "Atlantic": "Atlantique", "Central": "Centrale", "Pacific": "Pacifique", "Team": "Équipe", "Draft": "Repêchage", "Round 1": "1re ronde", "Round 2": "2e ronde",
  "Round 3": "3e ronde", "Round 4": "4e ronde", "Round 5": "5e ronde", "Round 6": "6e ronde", "Round 7": "7e ronde", "Trade protection": "Protection contre les échanges",
  "What matters to him": "Ce qui compte pour lui", "Make your pitch": "Votre argumentaire", "Sell him on home": "Lui vanter la ville natale",
  "Friends in the room": "Des amis dans le vestiaire", "A chance to win": "Une chance de gagner", "Patience": "Patience", "Mood": "Humeur",
  "Language": "Langue",
};
const FR_RE = [[/^◀ Back$/, "◀ Retour"], [/^Forward ▶$/, "Avancer ▶"], [/^Inbox \((\d+)\)$/, "Courrier ($1)"], [/^Press room \((\d+)\)$/, "Salle de presse ($1)"],
  [/^Board: (\w+) \((\d+)\)$/, "Conseil : $1 ($2)"], [/^Saves ▾$/, "Parties ▾"], [/^Forwards \((\d+)\)$/, "Attaquants ($1)"], [/^Defence \((\d+)\)$/, "Défense ($1)"],
  [/^Goalies \((\d+)\)$/, "Gardiens ($1)"], [/^Today: Game (vs|at) (\w+)$/, (m, a, b) => `Aujourd'hui : match ${a === "vs" ? "contre" : "à"} ${b}`]];
const FR_ATTR = {"Find a player or club": "Trouver un joueur ou un club", "Search mail": "Rechercher le courrier",
  "Console: any command (help lists them)": "Console : une commande (help les énumère)", "Player, club or staff name": "Joueur, club ou membre du personnel"};
const Lang = {
  get() { try { return localStorage.getItem("hmLang") || "en"; } catch (e) { return "en"; } },
  set(v) { try { localStorage.setItem("hmLang", v); } catch (e) { /* private window */ } location.reload(); },
  apply(root) {
    if (this.get() !== "fr") return;
    const walk = document.createTreeWalker(root || document.body, NodeFilter.SHOW_TEXT);
    const todo = [];
    while (walk.nextNode()) todo.push(walk.currentNode);
    for (const n of todo) {
      const t = n.nodeValue, k = t.trim();
      if (!k || !n.parentElement || n.parentElement.closest("script,style,textarea,pre")) continue;
      if (FR[k]) { n.nodeValue = t.replace(k, FR[k]); continue; }
      for (const [re, to] of FR_RE) if (re.test(k)) { n.nodeValue = t.replace(k, k.replace(re, to)); break; }
    }
    (root || document).querySelectorAll && (root || document).querySelectorAll("[placeholder],[title]").forEach((el) => {
      if (FR_ATTR[el.placeholder]) el.placeholder = FR_ATTR[el.placeholder];
      if (FR[el.title]) el.title = FR[el.title];
    });
  },
};
(function langMenu() {
  const file = MENUS[0][1];
  const at = file.findIndex((x) => Array.isArray(x) && x[0] === "Console");
  file.splice(at + 1, 0, ["Français (Québec)", () => Lang.set(Lang.get() === "fr" ? "en" : "fr"), () => Lang.get() === "fr"]);
  if (Lang.get() === "fr") {
    document.documentElement.lang = "fr-CA";
    let pending = false;
    new MutationObserver(() => { if (pending) return; pending = true; requestAnimationFrame(() => { pending = false; Lang.apply(document.body); }); })
      .observe(document.body, {childList: true, subtree: true, characterData: false});
    Lang.apply(document.body);
  }
})();

/* ---- boot: moved to the last script (v40.js) ---- */


/* ================================================================ report a bug (v58): the details a report needs, ready to send */
const BugReport = {
  email: "jeremy.legere@gmail.com",
  details() {
    const st = (typeof STATE !== "undefined" && STATE && STATE.loaded) ? `${STATE.team || ""} ${STATE.season || ""} ${STATE.date || ""}` : "no career loaded";
    return [`Hockey Manager version: ${APP.version || "?"}`, `Window: ${APP.desktop ? "desktop window" : "browser"}`,
            `System: ${navigator.platform || "?"} / ${navigator.userAgent}`, `Screen: ${location.hash || "#"}`, `Career: ${st}`,
            "", "What I did:", "", "What I expected:", "", "What happened instead:", ""].join("\n");
  },
  open() {
    const body = this.details();
    const href = `mailto:${this.email}?subject=${encodeURIComponent("Hockey Manager bug report (v" + (APP.version || "?") + ")")}&body=${encodeURIComponent(body)}`;
    Modal.open(`<div class="win-title">Report a bug</div><div class="pad about">
      <p>Thank you: reports are how this gets better. The more of this you can send, the faster it gets fixed:</p>
      <ol class="small"><li>What you did, what you expected, what happened instead (the details below are filled in for you).</li>
        <li>The error message, word for word, or a screenshot.</li>
        <li>If it is about a career: the save file from the <b>saves</b> folder (a plain <code>.db</code> file; it holds only that career's data). With it a bug can usually be replayed exactly.</li>
        <li>If you see "Traceback" in the terminal window the game was started from, paste it in.</li></ol>
      <textarea id="br-text" class="br-text" rows="11" readonly style="width:100%;font-family:monospace;font-size:12px">${esc(body)}</textarea>
      <p class="muted small">Send to <a href="${href}">${this.email}</a> (the button opens your mail program), or copy the text and email it yourself. If the game is on GitHub, an issue there works too.</p>
    </div><div class="win-buttons"><button class="primary" onclick="window.location.href=${esc(JSON.stringify(href))}">Open email</button>
      <button onclick="const t=$('#br-text');t.select();document.execCommand('copy');toast('Copied')">Copy details</button>
      <button onclick="Modal.close()">Close</button></div>`, "win");
  },
};
