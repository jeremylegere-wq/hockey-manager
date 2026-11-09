/* v51: League > International: tournaments, the world ranking, the medal table, the Triple Gold Club and our
   players (docs/INTERNATIONAL.md). */

const INT = {tab: "tournaments"};
VIEWS.intl = async (arg) => {
  const d = await api("intl", arg ? {tid: arg} : {});
  if (arg && d.detail) {
    const t = d.detail;
    const stages = {};
    t.games.forEach((g) => (stages[g.stage] = stages[g.stage] || []).push(g));
    const games = Object.entries(stages).map(([st, gs]) => `<h4>${esc(st)}</h4><table class="dv-t">${gs.map((g) => `<tr><td>${esc(g.home)}</td>
      <td class="num"><b>${g.hg}-${g.ag}</b>${g.ot === 1 ? " OT" : g.ot === 2 ? " SO" : ""}</td><td>${esc(g.away)}</td></tr>`).join("")}</table>`).join("");
    const rosters = Object.entries(t.rosters).sort((a, b) => (t.places.indexOf(a[0]) + 99) % 99 - (t.places.indexOf(b[0]) + 99) % 99).map(([n, rs]) =>
      `<details class="int-roster"><summary><b>${esc(n)}</b>${t.places.includes(n) ? ` <span class="muted">${["gold", "silver", "bronze"][t.places.indexOf(n)] || "#" + (t.places.indexOf(n) + 1)}</span>` : ""}
       <span class="muted small">${rs.length} players</span></summary><table class="dv-t">${rs.map((r) => `<tr${r.mine ? ' class="mine"' : ""}><td>${clink(r.player_id, r.name)}</td><td>${esc(r.pos)}</td><td>${esc(r.club)}</td></tr>`).join("")}</table></details>`).join("");
    return panel(esc(t.name), `<p>${t.status === "done" ? `<b>Gold:</b> ${esc(t.places[0])} · <b>Silver:</b> ${esc(t.places[1])} · <b>Bronze:</b> ${esc(t.places[2])}${t.mvp ? ` · MVP: ${clink(t.mvp.player_id, t.mvp.name)}` : ""}`
        : `Rosters named; the tournament is played ${esc(t.start)} to ${esc(t.end)}.`}</p>
      <div class="int-split"><div>${games || '<p class="muted">No games yet.</p>'}</div><div><h4>Scoring leaders</h4>${t.leaders.length ? table(t.leaders, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)},
        {key: "nation", label: "Nation"}, {key: "gp", label: "GP", num: 1}, {key: "g", label: "G", num: 1}, {key: "a", label: "A", num: 1}, {key: "p", label: "P", num: 1}]) : '<p class="muted">-</p>'}
        <h4>Rosters</h4>${rosters}</div></div><p><a href="#intl">Back to International</a></p>`);
  }
  const tabs = [["tournaments", "Tournaments"], ["ranking", "World ranking"], ["medals", "Medal table"], ["tgc", "Triple Gold Club"], ["ours", "Our players"]];
  let body = "";
  if (INT.tab === "tournaments") {
    body = (d.upcoming.length ? `<p>${d.upcoming.map((u) => `<span class="tag">${esc(u.name)}: ${dshort(u.start)} - ${dshort(u.end)}</span>`).join(" ")}</p>` : "") +
      (d.tournaments.length ? table(d.tournaments, [{key: "name", label: "Tournament", fmt: (r) => `<a href="#intl/${r.tid}">${esc(r.name)}</a>`},
        {key: "gold", label: "Gold", fmt: (r) => esc(r.podium[0] || (r.status === "done" ? "" : "to play"))}, {key: "silver", label: "Silver", fmt: (r) => esc(r.podium[1] || "")},
        {key: "bronze", label: "Bronze", fmt: (r) => esc(r.podium[2] || "")}, {key: "mvp", label: "MVP", fmt: (r) => r.mvp ? clink(r.mvp, r.mvp_name) : ""}])
        : empty("No tournament yet: the World Juniors start on 26 December."));
    if (d.banned.length) body += `<p class="muted small">Excluded (the IIHF ban): ${esc(d.banned.join(", "))}.</p>`;
  } else if (INT.tab === "ranking") {
    body = `<p class="muted small">IIHF style: World Championship and Olympic places over the last four years (100/75/50/25%); a seed from the real 2025 order fills the years before the save.</p>` +
      table(d.ranking.slice(0, 30), [{key: "rank", label: "#", num: 1}, {key: "nation", label: "Nation", fmt: (r) => esc(r.nation) + (r.banned ? ' <span class="muted small">(excluded)</span>' : "")}, {key: "points", label: "Points", num: 1}]);
  } else if (INT.tab === "medals") {
    body = d.medals.length ? `<table class="dv-t"><tr><th>Nation</th><th class="num">Gold</th><th class="num">Silver</th><th class="num">Bronze</th></tr>${d.medals.map((m) => `<tr><td>${esc(m[0])}</td><td class="num">${m[1]}</td><td class="num">${m[2]}</td><td class="num">${m[3]}</td></tr>`).join("")}</table>`
      : empty("No medals yet.");
  } else if (INT.tab === "tgc") {
    body = `<p class="muted small">Olympic gold, World Championship gold and an NHL championship, all won in this save.</p>` +
      (d.tgc.length ? table(d.tgc, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "day", label: "Joined", fmt: (r) => dshort(r.day)}]) : empty("Nobody yet."));
  } else {
    body = d.ours.length ? table(d.ours, [{key: "tournament", label: "Tournament"}, {key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)},
      {key: "nation", label: "Nation"}, {key: "result", label: "Result", fmt: (r) => ["gold", "silver", "bronze"].includes(r.result) ? `<span class="tag pos">${esc(r.result)}</span>` : esc(r.result)}])
      : empty("None of our players has played internationally in this save yet.");
  }
  AFTER = () => document.querySelectorAll("[data-inttab]").forEach((b) => b.onclick = () => { INT.tab = b.dataset.inttab; render(); });
  return panel("International", `<div class="toolbar"><div class="tabs">${tabs.map(([k, l]) => `<a class="btn${INT.tab === k ? " active" : ""}" data-inttab="${k}">${l}</a>`).join(" ")}</div></div>${body}`);
};
(() => {
  const lg = MENUS.find((m) => m[0] === "League")[1];
  const at = lg.findIndex((x) => Array.isArray(x) && x[0] === "College Hockey");
  lg.splice(at >= 0 ? at + 1 : lg.length, 0, ["International", "#intl"]);
  SCREEN_NAMES.intl = "International";
})();
Object.assign(FR, {"International": "International", "Tournaments": "Tournois", "World ranking": "Classement mondial", "Medal table": "Tableau des médailles",
  "Triple Gold Club": "Club Triple Or", "Our players": "Nos joueurs", "Tournament": "Tournoi", "Gold": "Or", "Silver": "Argent", "Bronze": "Bronze",
  "Nation": "Pays", "Joined": "Admis", "Back to International": "Retour à l'international", "Group A": "Groupe A", "Group B": "Groupe B", "Group C": "Groupe C",
  "Quarterfinal": "Quart de finale", "Semifinal": "Demi-finale", "Gold medal game": "Match pour la médaille d'or", "Bronze medal game": "Match pour la médaille de bronze",
  "Qualification": "Qualification", "No medals yet.": "Aucune médaille pour l'instant.", "Nobody yet.": "Personne pour l'instant."});

/* v52: lineups - priority lists that rebuild the lines before every game, and the goalie rule (docs/LINES.md) */
const LUPV = {open: false};
const linesV52 = VIEWS.lines;
VIEWS.lines = async (...args) => {
  const html = await linesV52(...args);
  const prev = AFTER;
  let d;
  try { d = await api("lineups"); } catch (e) { return html; }
  const names = {C: "Centres", LW: "Left wings", RW: "Right wings", LD: "Left defence", RD: "Right defence", G: "Goalies", PP: "Power play (10)", PK: "Penalty kill (8)"};
  const ruleNames = {usual: "usual (the first starts about 82%)", every_game: "the first starts every game", back_to_back: "rest the first on back-to-backs", every_fourth: "the second every fourth game"};
  const list = (k) => {
    const xs = d.lists[k] || [];
    const pool = d.roster.filter((p) => (k === "G") === (p.pos === "G") && !xs.some((x) => x.player_id === p.player_id));
    return `<div class="lu-list"><h4>${esc(names[k])}</h4><ol>${xs.map((x, i) => `<li><span class="${x.status === "active" ? "" : "muted"}">${esc(x.name)} <span class="muted small">${esc(x.pos)}${x.status === "active" ? "" : " · " + esc(x.status)}</span></span>
      <span class="lu-btns"><a class="lu-mv" data-k="${k}" data-i="${i}" data-d="-1" title="Up">▲</a><a class="lu-mv" data-k="${k}" data-i="${i}" data-d="1" title="Down">▼</a><a class="lu-rm" data-k="${k}" data-i="${i}" title="Remove">✕</a></span></li>`).join("")}</ol>
      ${pool.length ? `<select class="lu-add" data-k="${k}"><option value="">add...</option>${pool.map((p) => `<option value="${p.player_id}">${esc(p.name)} (${p.pos})</option>`).join("")}</select>` : ""}</div>`;
  };
  const body = `<div class="toolbar"><label class="chk"><input type="checkbox" id="lu-on"${d.enabled ? " checked" : ""}> Rebuild my lines from these lists before every game</label>
      <label>Goalie rule <select id="lu-g">${d.rules.map((r) => `<option value="${r}"${r === d.goalie_rule ? " selected" : ""}>${esc(ruleNames[r] || r)}</option>`).join("")}</select></label>
      <span class="spacer"></span><a class="btn" id="lu-tog">${LUPV.open ? "Hide the lists" : "Edit the lists"}</a></div>
    <p class="muted small">The first healthy player on each list who is not already used takes the slot (centres first, then wings line by line, then the pairs); a list that runs out is filled with the best remaining player. ${d.enabled ? "With lineups on, lines you set by hand last until the next game." : ""}</p>
    ${LUPV.open ? `<div class="lu-grid">${["C", "LW", "RW", "LD", "RD", "G", "PP", "PK"].map(list).join("")}</div>` : ""}`;
  AFTER = () => {
    if (prev) prev();
    const save = async (k, ids) => { const r = await cmd(`lineups list ${k} ${ids.join(", ")}`, {quiet: true}); if (r.ok) render(); };
    const ids = (k) => (d.lists[k] || []).map((x) => x.player_id);
    $("#lu-on").onchange = async (e) => { await cmd(`lineups ${e.target.checked ? "on" : "off"}`); render(); };
    $("#lu-g").onchange = async (e) => { await cmd(`lineups goalie ${e.target.value}`, {quiet: true}); };
    $("#lu-tog").onclick = () => { LUPV.open = !LUPV.open; render(); };
    document.querySelectorAll(".lu-mv").forEach((a) => a.onclick = () => {
      const k = a.dataset.k, i = +a.dataset.i, j = i + +a.dataset.d, xs = ids(k);
      if (j < 0 || j >= xs.length) return;
      [xs[i], xs[j]] = [xs[j], xs[i]]; save(k, xs);
    });
    document.querySelectorAll(".lu-rm").forEach((a) => a.onclick = () => { const xs = ids(a.dataset.k); xs.splice(+a.dataset.i, 1); save(a.dataset.k, xs); });
    document.querySelectorAll(".lu-add").forEach((s) => s.onchange = () => { if (s.value) save(s.dataset.k, [...ids(s.dataset.k), +s.value]); });
  };
  return panel("Lineups", body) + html;
};
Object.assign(FR, {"Lineups": "Formations", "Centres": "Centres", "Left defence": "Défense gauche", "Right defence": "Défense droite",
  "Power play (10)": "Avantage numérique (10)", "Penalty kill (8)": "Désavantage numérique (8)", "Edit the lists": "Modifier les listes", "Hide the lists": "Masquer les listes",
  "Rebuild my lines from these lists before every game": "Refaire mes trios à partir de ces listes avant chaque match", "Goalie rule": "Règle des gardiens"});

/* v53: League > Discipline, and the player page's suspension tag (docs/DISCIPLINE.md) */
VIEWS.discipline = async () => {
  const d = await api("discipline");
  const cols = [{key: "day", label: "Date", fmt: (r) => dshort(r.day)}, {key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)},
    {key: "team", label: "Club"}, {key: "games", label: "Games", num: 1}, {key: "left", label: "Left", num: 1}, {key: "reason", label: "For"},
    {key: "forfeit", label: "Forfeits", num: 1, fmt: (r) => r.forfeit ? mil(r.forfeit) : "-"},
    {key: "appeal", label: "Appeal", fmt: (r) => r.can_appeal ? `<button data-cmd="discipline appeal ${r.player_id}">Appeal</button>` : esc(r.appeal || "")}];
  return panel("Suspended now", d.active.length ? table(d.active, cols) : empty("Nobody is suspended.")) +
    panel("Supplementary discipline", `<p class="muted small">About one NHL game in thirty brings a suspension. A suspension of ${d.appeal_min}+ games can be appealed once.</p>` +
      (d.log.length ? table(d.log, cols) : empty("No suspensions yet.")));
};
(() => {
  const lg = MENUS.find((m) => m[0] === "League")[1];
  const at = lg.findIndex((x) => Array.isArray(x) && x[0] === "International");
  lg.splice(at >= 0 ? at + 1 : lg.length, 0, ["Discipline", "#discipline"]);
  SCREEN_NAMES.discipline = "Discipline";
})();
const playerV53 = VIEWS.player;
VIEWS.player = async (id) => {
  const html = await playerV53(id);
  const p = await api("player", {id});
  return p.suspended ? html.replace('<div class="pp-tags">', `<div class="pp-tags"><span class="pp-tag neg">Suspended: ${p.suspended} game${p.suspended === 1 ? "" : "s"}</span>`) : html;
};
Object.assign(FR, {"Discipline": "Discipline", "Suspended now": "Suspendus", "Supplementary discipline": "Sanctions supplémentaires", "Games": "Matchs",
  "Left": "Restants", "For": "Pour", "Forfeits": "Perd", "Appeal": "Appel", "Nobody is suspended.": "Personne n'est suspendu.", "No suspensions yet.": "Aucune suspension pour l'instant."});

/* ---- boot: moved to the last script (v54.js) ---- */
