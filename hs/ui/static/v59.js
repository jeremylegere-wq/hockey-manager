"use strict";
// v59: watch your own game in 2D before you know the score (docs/RINK2D.md "Watching your game").
// On a game day the bar at the bottom offers "Watch in 2D": the day is played, and your game opens in a window of
// its own from the opening draw, with the score building as it happens. Close it (or wait for the final) and the
// day's results are there as usual.
const refreshV59 = refresh;
refresh = async function () {
  await refreshV59();
  const c = $("#sb-controls");
  if (!c || !STATE || !STATE.started || STATE.unemployed || STATE.phase !== "regular_season") return;
  if (!/^Game /.test((STATE.strip && STATE.strip.event) || "") || c.querySelector("#sb-watch")) return;
  const nx = c.querySelector('[data-sim="next"]');
  if (!nx) return;
  nx.insertAdjacentHTML("beforebegin", '<button id="sb-watch" title="Play today and watch your game on the rink">Watch in 2D</button> ');
  $("#sb-watch").onclick = watchToday;
};
async function watchToday() {
  const today = STATE.date;
  setBusy(true);
  let gid = null;
  try {
    await post("/api/sim", {mode: "day", pace: 0});
    let since = 0;
    for (let i = 0; i < 600; i++) {
      const s = await (await fetch(`/api/simstatus?since=${since}`)).json();
      since = s.next;
      if (!s.running) { if (s.error) throw new Error(s.error); break; }
      await new Promise((r) => setTimeout(r, 200));
    }
    const st = await api("state");                          // the day is played: which game was ours?
    const d = ((st.strip || {}).days || []).find((x) => x.date === today && x.game_id && x.result);
    if (d) gid = d.game_id;
  } catch (err) { setBusy(false); toast(err.message, true); return refresh(); }
  setBusy(false);
  if (gid == null) { toast("Your game was not played (the day stopped for something that needs you)."); return refresh(); }
  try { await Ice.watch(gid, () => refresh()); } catch (err) { toast("The 2D game could not be built: " + err.message, true); refresh(); }
}
/* ---- the lines screen: drag one place onto another to swap them; lock a player to his place (v59) ---- */
const linesV59 = VIEWS.lines;
VIEWS.lines = async (...args) => {
  const html = await linesV59(...args);
  const prev = AFTER;
  AFTER = async () => {
    if (prev) await prev();
    let lv = {locks: [], enabled: false};
    try { lv = await api("lineups"); } catch (e) { /* no lists yet */ }
    const locked = Object.fromEntries((lv.locks || []).map((x) => [x.slot, x.player_id]));
    const POS = {F: ["C", "LW", "RW"], D: ["LD", "RD"]};
    let from = null;
    document.querySelectorAll('select.ln[data-unit^="F"], select.ln[data-unit^="D"]').forEach((sel) => {
      const td = sel.closest("td"), unit = sel.dataset.unit, i = +sel.dataset.i, slot = `${unit}:${i}`;
      if (!td || td.querySelector(".ln-grip")) return;
      td.classList.add("ln-cell");
      const lab = td.querySelector("span.muted");
      lab.insertAdjacentHTML("afterend", ` <span class="ln-grip" draggable="true" title="Drag onto another place to swap the two players">&#8942;&#8942;</span>
        <button type="button" class="ln-lock${locked[slot] ? " on" : ""}" title="A locked player keeps this place when your lineup lists rebuild the lines">${locked[slot] ? "locked" : "lock"}</button>`);
      const grip = td.querySelector(".ln-grip"), lock = td.querySelector(".ln-lock");
      grip.addEventListener("dragstart", (e) => { from = sel; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", slot); td.classList.add("drag"); });
      grip.addEventListener("dragend", () => { td.classList.remove("drag"); document.querySelectorAll(".ln-cell.over").forEach((x) => x.classList.remove("over")); });
      td.addEventListener("dragover", (e) => { if (from && from !== sel) { e.preventDefault(); td.classList.add("over"); } });
      td.addEventListener("dragleave", () => td.classList.remove("over"));
      td.addEventListener("drop", (e) => {
        e.preventDefault(); td.classList.remove("over");
        if (!from || from === sel) return;
        const fs = `${from.dataset.unit}:${from.dataset.i}`;
        if (locked[slot] || locked[fs]) { from = null; return toast("One of those places is locked. Unlock it first.", true); }
        const a = from.value, b = sel.value; from.value = b; sel.value = a; from = null;
        sel.dispatchEvent(new Event("change")); toast("Swapped. Save lines to keep it.");
      });
      lock.onclick = async () => {
        const on = lock.classList.contains("on");
        if (!on && !sel.value) return toast("Nobody is in that place.", true);
        try {
          await post("/api/command", {line: on ? `lineups unlock ${locked[slot] || sel.value}` : `lineups lock ${sel.value} ${unit} ${POS[unit[0]][i]}`});
          if (on) delete locked[slot]; else { for (const k of Object.keys(locked)) if (String(locked[k]) === String(sel.value)) { delete locked[k];
            const o = document.querySelector(`select.ln[data-unit="${k.split(":")[0]}"][data-i="${k.split(":")[1]}"]`); if (o) { const ob = o.closest("td").querySelector(".ln-lock"); ob.classList.remove("on"); ob.textContent = "lock"; } }
            locked[slot] = sel.value; }
          lock.classList.toggle("on", !on); lock.textContent = on ? "lock" : "locked";
          toast(on ? "Unlocked." : (lv.enabled ? "Locked: he keeps this place when the lists rebuild your lines." : "Locked. Locks apply when Lineups are on."));
        } catch (err) { toast(err.message, true); }
      };
    });
  };
  return html;
};
/* ---- two more reports: league demographics, and each draft looked at again (v59) ---- */
REP.splice(REP.length - 1, 0, ["demographics", "Demographics"], ["redraft", "Draft: steals and reaches"]);
const reportsV59 = VIEWS.reports;
VIEWS.reports = async (kind = "positional") => {
  if (kind !== "demographics" && kind !== "redraft") return reportsV59(kind);
  const d = await api("reports", Object.assign({kind}, kind === "redraft" && window.RD_YEAR ? {year: window.RD_YEAR} : {}));
  const tabs = tabBar(REP.map(([k, l]) => [k, l, k === "power" ? "#news/power" : `#reports/${k}`]), d.kind);
  const mine = {rowClass: (r) => STATE && r.team_id === STATE.team_id ? "mine" : ""};
  const barCell = (r) => `<span class="chem"><i style="width:${Math.min(100, r.pct * 2)}%"></i></span> ${r.pct}%`;
  if (kind === "demographics") {
    return tabs + `<div class="grid three">${panel(`Where the league's ${d.players} players come from`, `<div class="scroll tall">${table(d.nations, [{key: "nation", label: "Nation"}, {key: "n", label: "Players", num: true}, {key: "pct", label: "Share", fmt: barCell}])}</div>`)}
      ${panel("Ages", table(d.ages, [{key: "band", label: "Age"}, {key: "n", label: "Players", num: true}, {key: "pct", label: "Share", fmt: barCell}]))}
      ${panel("Club by club, youngest first", `<div class="scroll tall">${table(d.clubs, [{key: "team", label: "Club", fmt: (r) => tm(r.team, r.team_id)}, {key: "age", label: "Avg age", num: true},
        {key: "height", label: "Height (cm)", num: true}, {key: "weight", label: "Weight (kg)", num: true}, {key: "nations", label: "Nations", num: true}, {key: "n", label: "Players", num: true}], mine)}</div>`)}</div>`;
  }
  if (!d.year) return tabs + panel("Draft: steals and reaches", '<p class="muted">No draft has been held in this career yet.</p>');
  const cols = [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "pos", label: "Pos"}, {key: "team", label: "Picked by", fmt: (r) => tm(r.team, r.team_id)},
    {key: "overall", label: "Pick", num: true}, {key: "now", label: "Today", num: true}, {key: "move", label: "Change", num: true, fmt: (r) => `<span class="${r.move > 0 ? "pos" : "neg"}">${r.move > 0 ? "+" : ""}${r.move}</span>`},
    {key: "potential", label: "Potential", fmt: (r) => r.potential != null ? potentialStars(r.potential) : ""}];
  if (d.years && d.years.length > 1) {                      // v61: any past draft
    AFTER = () => { const s = $("#rd-year"); if (s) s.onchange = () => { window.RD_YEAR = +s.value; render(); }; };
  }
  const yearSel = d.years && d.years.length > 1 ? ` <select id="rd-year">${d.years.map((y) => `<option value="${y}"${y === d.year ? " selected" : ""}>${y}</option>`).join("")}</select>` : "";
  return tabs + `<p class="muted">Draft${yearSel}: the ${d.year} draft, picked again today on potential first, then ability (your scouts' view). "Today" is where he would go now.</p>
    <div class="grid two">${panel("Steals: picked later than they would go today", table(d.steals, cols, mine))}${panel("Reaches: first two rounds, picked earlier than they would go today", table(d.reaches, cols, mine))}</div>`;
};
/* ---- v60: which leagues play game by game (World Leagues > Leagues in play) ---- */
VIEWS.leagueplay = async () => {
  const d = await api("leagueplay");
  const on = d.filter((x) => x.play).length;
  const lv = {2: "Leading leagues", 3: "Other professional leagues", 4: "Junior and university"};
  const groups = {};
  d.forEach((x) => (groups[x.level] = groups[x.level] || []).push(x));
  const body = Object.keys(groups).sort().map((k) => `<h4>${esc(lv[k] || "Level " + k)}</h4>` + table(groups[k], [
    {key: "abbr", label: "League", fmt: (r) => `<a href="#worldleagues/${r.league_id}"><b>${esc(r.abbr)}</b></a> ${esc(r.name)}`},
    {key: "clubs", label: "Clubs", num: true}, {key: "games", label: "Games", num: true},
    {key: "approximate", label: "Format", fmt: (r) => r.approximate ? '<span class="tag warn" title="Game count, points and playoff size are approximations, not from the league">approximate</span>' : "the league's own"},
    {key: "play", label: "Played", fmt: (r) => `<select data-lgplay="${esc(r.abbr)}"><option value="on"${r.play ? " selected" : ""}>Game by game</option><option value="off"${r.play ? "" : " selected"}>A season at a time</option></select>`
      + (r.affiliates && !r.play ? ' <span class="tag warn">your farm clubs play here</span>' : "")}])).join("");
  AFTER = () => {
    document.querySelectorAll("[data-lgplay]").forEach((s) => (s.onchange = () => cmd(`leagues play ${s.dataset.lgplay} ${s.value}`)));
    document.querySelectorAll("[data-lgall]").forEach((b) => (b.onclick = () => cmd(`leagues play ${b.dataset.lgall}`)));
  };
  return `<div class="tabs"><a class="btn" href="#worldleagues">&larr; World Leagues</a><span class="spacer"></span>
      <button data-lgall="all">All game by game</button> <button data-lgall="core">Verified formats only</button> <button data-lgall="none">None (fastest)</button></div>`
    + panel(`Leagues in play: ${on} of ${d.length} game by game`, `<p class="muted">A league played game by game has a schedule, standings, playoffs and box-score statistics, and costs a little time every day.
      A league simulated a season at a time gets its statistics and a champion when the year ends, and costs nothing during the season. Changing a league takes effect at once: switching one on
      schedules it and catches it up to today; switching one off takes back what it has played this season. Your own league is always played in full.</p>${body}`);
};
const worldLeaguesV60 = VIEWS.worldleagues;
VIEWS.worldleagues = async (...a) => (await worldLeaguesV60(...a)).replace('<div class="wl-grp">', '<div class="wl-grp"><a class="btn" href="#leagueplay">Leagues in play...</a></div><div class="wl-grp">');
if (typeof SCREEN_NAMES !== "undefined") SCREEN_NAMES.leagueplay = "Leagues in play";
Object.assign(FR, {"Watch in 2D": "Regarder en 2D", "Full window": "Pleine fenêtre", "Leave full window": "Quitter la pleine fenêtre", "Goals only": "Buts seulement",
  "Whole rink": "Toute la patinoire", "Follow the play": "Suivre le jeu", "Camera": "Caméra", "Names": "Noms", "Play by play": "Jeu par jeu", "Box score": "Sommaire", "lock": "verrouiller", "locked": "verrouillé", "Demographics": "Démographie", "Draft: steals and reaches": "Repêchage : aubaines et paris", "Ages": "Âges", "Leagues in play": "Ligues en jeu", "Game by game": "Match par match", "A season at a time": "Une saison à la fois", "Leagues in play...": "Ligues en jeu..."});

/* ---- v61: performance bonuses for 35+ and injured veterans on one-year deals ---- */
Talks.perf = 0;
const talksRenderV61 = Talks.render.bind(Talks);
Talks.render = function (v) {
  talksRenderV61(v);
  const raw = (v && v._raw) || v;
  if (!raw || !raw.open || !raw.perf) return;
  const anchor = document.querySelector(".tk-structure") || document.querySelector(".tk-offer .row");
  if (!anchor) return;
  const one = +this.years === 1;
  anchor.insertAdjacentHTML("afterend", `<div class="tk-perf"><label>Performance bonuses <input id="tk-perf" type="number" min="0" step="250000" value="${one ? this.perf || 0 : 0}" ${one ? "" : "disabled"} style="width:9em"></label>
    <span class="muted small">${esc(raw.perf.text)} ${one ? `Bonuses are not in the cap hit until earned (games, points, the playoffs); he counts each dollar as about ${Math.round(raw.perf.value * 100)} cents of salary. Earned bonuses past the cap come off next season's.` : "Only on a one-year deal."}</span></div>`);
  $("#tk-perf").onchange = (e) => { this.perf = Math.max(0, +e.target.value || 0); };
};
Talks.send = async function () {
  const box = $("#tk-log");
  const prot = this.clause && this.clause !== "none" ? this.clause : "";
  const st = this.structure && this.structure !== "flat" ? this.structure : "";
  const pf = +this.years === 1 && this.perf > 0 ? Math.round(this.perf) : 0;
  box.insertAdjacentHTML("beforeend", `<div class="bub you"><div class="who">You</div>${this.years} yr x ${mil(this.aav)}${pf ? ` + up to ${mil(pf)} in bonuses` : ""}${st === "front" ? ", front-loaded" : st === "bonus" ? ", bonus-heavy" : ""}${prot ? " with trade protection" : ""}</div><div class="bub agent typing"><i></i><i></i><i></i></div>`);
  box.scrollTop = box.scrollHeight;
  document.querySelectorAll(".tk-offer button").forEach((b) => b.disabled = true);
  const r = await quietCmd(`propose ${this.pid} ${Math.round(this.aav)} ${this.years}${st ? " " + st : ""}${prot ? " " + prot : ""}${pf ? " perf=" + pf : ""}`);
  await new Promise((res) => setTimeout(res, 650));
  if (!r.ok) toast(r.output, true);
  this.render(await api("negotiation", {id: this.pid}));
};
const playerV61 = VIEWS.player;
VIEWS.player = async (id) => {
  const html = await playerV61(id);
  const prev = AFTER;
  AFTER = async () => {
    if (prev) await prev();
    if ((location.hash.split("/")[2] || "") !== "contract") return;
    const p = await api("player", {id}).catch(() => null);
    if (!p || !p.perf_bonus) return;
    const b = p.perf_bonus;
    const parts = b.parts ? ["10 games", "41 games (25 for a goalie)", "the points (or save %) mark", "the playoffs"].filter((_, i) => b.parts[i] === "1") : [];
    $("#view").insertAdjacentHTML("beforeend", panel("Performance bonuses", `<p>${b.kind === "35+" ? "A 35+ one-year deal" : "An injured veteran's one-year deal"}: up to <b>${mil(b.max)}</b> in performance bonuses, not counted in the cap hit until earned.
      ${b.earned == null ? "Earned at season end, a quarter each for 10 games, 41 games (25 for a goalie), 25 points for a forward / 15 for a defenceman (a .905 save percentage for a goalie) and the playoffs." : `Earned: <b>${mil(b.earned)}</b>${parts.length ? ` (${esc(parts.join(", "))})` : ""}.`}</p>`));
  };
  return html;
};

/* ---- v61: the needs tab on the trade screen ---- */
const tradeV61 = VIEWS.trade;
VIEWS.trade = async (team) => {
  const html = await tradeV61(team);
  if (!team) return html;
  const d = await api("trade", {team}).catch(() => null);
  const n = d && d.needs_tab;
  if (!n) return html;
  const gname = {F: "Forwards", D: "Defence", G: "Goal"};
  const room = (x) => x == null ? "-" : (x < 0 ? `<span class="neg">${mil(x)}</span>` : mil(x));
  const side = (s, who) => `<table class="dv-t"><tr><th>${esc(who)}</th><th class="num">Need</th><th></th><th class="num">Players</th></tr>
    ${["F", "D", "G"].map((g) => { const x = s.groups[g]; return `<tr><td>${gname[g]}</td><td class="num"><b>${x.need}</b></td>
      <td class="small ${x.need >= 60 ? "neg" : ""}">${esc(x.word)}${x.surplus ? " · deep: can spare one" : ""}</td><td class="num">${x.players}</td></tr>`; }).join("")}</table>
    <p class="small muted">${esc(s.abbr)}: ${esc(s.posture)}${s.rank ? ` (${s.rank} in the league)` : ""} · cap room ${room(s.cap_room)} now, ${room(s.cap_room_next)} next season</p>`;
  const fits = n.fits.length ? table(n.fits, [{key: "name", label: "Your player", fmt: (r) => clink(r.player_id, r.name)}, {key: "pos", label: "Pos"},
      {key: "role", label: "Would play"}, {key: "value", label: "Value", num: true}, {key: "cap", label: "Cap hit", num: true, fmt: (r) => r.cap ? mil(r.cap) : "-"}])
    : '<p class="muted small">They have no hole one of your players would fill.</p>';
  const get = n.gettable.length ? table(n.gettable, [{key: "name", label: "Their player", fmt: (r) => clink(r.player_id, r.name)}, {key: "pos", label: "Pos"},
      {key: "word", label: "To get", fmt: (r) => `<span class="${r.word === "hard" ? "neg" : r.word === "available" ? "pos" : ""}" title="how hard he is to pry loose: ${r.friction}/100">${esc(r.word)}</span>`},
      {key: "value", label: "Value", num: true}, {key: "cap", label: "Cap hit", num: true, fmt: (r) => r.cap ? mil(r.cap) : "-"},
      {key: "ends", label: "Ends", num: true, fmt: (r) => r.ends ? ssn(r.ends - 1) : "-"}, {key: "helps_you", label: "", fmt: (r) => r.helps_you ? '<span class="tag">fills a need of yours</span>' : ""}])
    : '<p class="muted small">Nobody there is easy to pry loose.</p>';
  return html + panel(`Needs: ${esc(n.them.abbr)} and you`, `<div class="grid two"><div>${side(n.them, n.them.abbr)}<p class="small">They want ${esc(n.them.wants)}.</p></div>
      <div>${side(n.you, n.you.abbr + " (you)")}</div></div>
    <div class="grid two"><div><h4>Your players who would fill their holes</h4>${fits}</div><div><h4>Their players who could be had</h4>${get}</div></div>
    <p class="muted small">From the picture their trade AI works from: need 0-100 by position (depth against a playoff club's, prospects, injuries), their posture, and how hard each player is to pry loose (value, term, cap share, clauses, letters).</p>`);
};
Object.assign(FR, {"Their player": "Leur joueur", "Your player": "Votre joueur", "Would play": "Jouerait", "To get": "À obtenir"});

/* ---- v61: running a European club (docs/EUROPE.md) ---- */
["euclub", "worldleagues", "leagueplay"].forEach((v) => UNEMPLOYED_VIEWS.add(v));
const renderV61 = render;
render = async function () {
  const out = await renderV61();
  if (STATE && STATE.eu_club) {
    const pill = document.querySelector("#sb-controls a.pill.link");
    if (pill) { pill.textContent = `Your club: ${STATE.eu_club.name} (${STATE.eu_club.league})`; pill.href = "#dashboard"; }
  }
  return out;
};
(() => {
  const lg = MENUS.find((m) => m[0] === "League")[1];
  const at = lg.findIndex((x) => Array.isArray(x) && x[0] === "World Leagues");
  lg.splice(at >= 0 ? at + 1 : lg.length, 0, ["European club", "#euclub"]);
  SCREEN_NAMES.euclub = "European club";
})();
const updateHeaderV61 = updateHeader;
updateHeader = function () {
  updateHeaderV61();
  const eu = !!(STATE && STATE.eu_club);
  if (eu) { $("#tb-team").textContent = STATE.eu_club.name; $("#sh-record").textContent = `${STATE.eu_club.league} · ${typeof tr === "function" ? tr("reputation") : "reputation"} ${Math.round(STATE.reputation)}`; }
  // the tabs a European club uses under their European names (Trade is the transfer market)
  [["trade", "Transfers"]].forEach(([v, l]) => {
    const a = document.querySelector(`#nav a[data-view="${v}"]`);
    if (!a) return;
    if (!a.dataset.nhl) a.dataset.nhl = a.textContent;
    a.textContent = eu ? tr(l) : a.dataset.nhl;
  });
};
const EUC = {type: "transfer", f: {pos: "", age: "", fee: "", free: ""}};
const eur = (x) => x == null ? "-" : money(x, "EUR");
const euJobsTable = (j) => j.jobs.length ? table(j.jobs, [{key: "name", label: "Club"}, {key: "league", label: "League"},
    {key: "demand", label: "Reputation wanted", num: true}, {key: "chance", label: "Your chance", num: true, fmt: (r) => `${Math.round(r.chance * 100)}%`},
    {key: "x", label: "", fmt: (r) => r.last_applied && STATE && r.last_applied.slice(0, 7) === STATE.date.slice(0, 7) ? '<span class="muted">interviewed this month</span>'
      : `<button class="mini primary" data-cmd="club apply ${r.team_id}" data-confirm="Apply to coach ${esc(r.name)}?">Apply</button>`}])
  : empty("No European club is looking for a coach right now. Openings come each summer, when clubs that fell short of their squad part with their coach.");
// League > European club: choose a club (a new European career) or the openings; while you run one, its Office
VIEWS.euclub = async () => {
  const d = await api("euclub");
  if (d.active) { location.replace("#dashboard"); return ""; }
  if (!d.jobs.free_choice) {
    return panel("European openings", `<p>Your reputation: <b>${Math.round(d.jobs.reputation)}</b>. A club wants a coach whose reputation fits it (the bigger the club and its league, the more it wants); each club interviews you once a month.</p>` + euJobsTable(d.jobs));
  }
  const groups = {};
  d.clubs.forEach((c) => (groups[c.league] = groups[c.league] || []).push(c));
  return panel("Manage in Europe", `<p>Take a job with a club in any European league that plays game by game. You leave your NHL club if you have one; the NHL plays on, and you can apply for NHL jobs later (Job Centre).
    There is no draft and there are no trades in Europe: you recruit (free agents, transfers, loans) and an academy brings youngsters up each September.</p>
    ${Object.entries(groups).map(([lg, cs]) => `<h4>${esc(lg)}</h4><p>${cs.map((c) => `<button class="mini" data-cmd="club start ${c.team_id}" data-confirm="Take the job at ${esc(c.name)}?${STATE && STATE.team_id ? " You will leave your NHL club." : ""}">${esc(c.name)}</button>`).join(" ")}</p>`).join("")}`);
};
// the club's screens behind the game's own tabs: Office (the board), Roster, Contracts, Trade (transfers), Transactions
const euHead = (d) => {
  const b = d.budget;
  return `<div class="eu-head"><b>${esc(d.name)}</b> <span class="muted">${esc(d.league)} · ${d.place ? ordinal(d.place) + " of " + d.clubs_in_league : "season not started"}</span>
    <span class="tag ${d.window ? "pos" : "warn"}">window ${d.window ? "open (to 15 Feb)" : "shut (opens 1 July)"}</span>
    <span>Transfer budget <b>${eur(b.transfer_budget)}</b></span> <span>Wages <b>${eur(d.wage_bill)}</b> of ${eur(b.wage_budget)}</span>
    <a class="btn" href="#worldleagues/${d.league_id}">League table</a></div>`;
};
const euContract = (r, d) => r.loan_from ? `on loan from ${esc(r.loan_from)} to ${esc(r.loan_until)}` : r.nhl ? '<span class="muted">NHL-held</span>'
  : r.until ? (r.until <= d.season ? `<span class="neg" title="Extend him before 1 July or he leaves">ends this summer</span>` : `to ${ssn(r.until)}`) : "-";
const euOffers = (d) => d.offers.length ? table(d.offers, [{key: "player", label: "Player", fmt: (r) => clink(r.player_id, r.player)}, {key: "club", label: "From"},
    {key: "fee", label: "Fee", num: true, fmt: (r) => eur(r.fee)}, {key: "wage", label: "His wage there", num: true, fmt: (r) => eur(r.wage)}, {key: "day", label: "Made"},
    {key: "x", label: "", fmt: (r) => `<button class="mini primary" data-cmd="club offer ${r.offer_id} accept" data-confirm="Sell ${esc(r.player)} for ${eur(r.fee)}?">Accept</button> <button class="mini" data-cmd="club offer ${r.offer_id} reject">Reject</button>`}]) : "";
async function euScreen(tab) {
  const d = await api("euclub");
  if (!d.active) return VIEWS.euclub();
  let html = "";
  if (tab === "board") {
    const B = d.board;
    html = (d.offers.length ? panel(`Offers for your players (${d.offers.length})`, euOffers(d)) : "")
      + panel("The board", B ? `<p>The board expects <b>a top-${B.target} finish</b>${B.title ? " <b>and the title</b>" : ""}. ${d.place ? `You are ${ordinal(d.place)}.` : ""}</p>
        <p>Board confidence <b>${Math.round(B.confidence)}</b>/100</p>${bar(B.confidence)}${B.note ? `<p class="muted">Last season: ${esc(B.note)}</p>` : ""}
        <p class="muted small">Confidence moves each month with your place against the target (and falls if the wage bill is over budget). At the end of the season the board reviews it: at 20 or below you are sacked.</p>
        <p><a class="btn" href="#lines">Lineup</a> <a class="btn" href="#tactics">Tactics</a> <a class="btn" href="#trade">Transfers</a> <a class="btn" href="#contracts">Contracts</a></p>` : "")
      + panel("European openings", euJobsTable(d.jobs));
  } else if (tab === "squad") {
    html = panel("Squad", table(d.squad, [{key: "pos", label: "Pos"}, {key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "age", label: "Age", num: true},
      {key: "nat", label: "Nat"}, {key: "overall", label: "Ability", num: true}, {key: "until", label: "Contract", fmt: (r) => euContract(r, d)}]))
      + (d.out_on_loan.length ? panel("Out on loan", table(d.out_on_loan, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "club", label: "At"},
        {key: "until", label: "Until"}, {key: "x", label: "", fmt: (r) => `<button class="mini" data-cmd="club recall ${r.player_id}">Recall</button>`}])) : "");
  } else if (tab === "contracts") {
    const lend = `<option value="">Lend to...</option>` + d.lend_to.map((c) => `<option value="${c.team_id}">${esc(c.name)} (${esc(c.league)})</option>`).join("");
    const rows = d.squad.slice().sort((a, b) => (b.wage || 0) - (a.wage || 0));
    html = panel("Contracts", `<p class="muted small">Wages a season. A contract that ends this summer must be extended before 1 July, or the player leaves as a free agent. Releasing a player pays out half of what is left on his deal, from the transfer budget.</p>`
      + table(rows, [{key: "pos", label: "Pos"}, {key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "age", label: "Age", num: true},
        {key: "overall", label: "Ability", num: true},
        {key: "wage", label: "Wage", num: true, fmt: (r) => r.loan_from ? `<span class="muted">on loan</span>` : r.nhl ? '<span class="muted">NHL-held</span>' : eur(r.wage)},
        {key: "until", label: "Contract", fmt: (r) => euContract(r, d)}, {key: "renew_ask", label: "Wants to stay", num: true, fmt: (r) => r.renew_ask ? eur(r.renew_ask) : ""},
        {key: "x", label: "", fmt: (r) => r.loan_from || r.nhl ? "" : `<button class="mini" data-eurenew="${r.player_id}" data-ask="${r.renew_ask || 0}">Extend</button>
          <select class="mini" data-eulend="${r.player_id}">${lend}</select>
          <button class="mini" data-cmd="club release ${r.player_id}" data-confirm="Release ${esc(r.name)}? Half of what is left on his deal is paid out.">Release</button>`}]));
  } else if (tab === "market") {
    const q = Object.assign({}, EUC.f.pos ? {pos: EUC.f.pos} : {}, EUC.f.age ? {age: EUC.f.age} : {}, EUC.f.fee ? {fee: EUC.f.fee} : {}, EUC.f.free ? {free: "1"} : {});
    const m = await api("eumarket", q);
    const sel = (k, opts) => `<select data-euf="${k}">${opts.map(([v, l]) => `<option value="${v}"${String(EUC.f[k]) === String(v) ? " selected" : ""}>${l}</option>`).join("")}</select>`;
    const cur = currencyCode();
    const fees = [0, 50000, 150000, 400000, 1000000];
    const filters = `<div class="toolbar"><div class="tabs"><a class="btn${EUC.type === "transfer" ? " active" : ""}" data-eutype="transfer">Transfer</a> <a class="btn${EUC.type === "loan" ? " active" : ""}" data-eutype="loan">Loan</a></div>
      ${sel("pos", [["", "Any position"], ["F", "Forwards"], ["C", "C"], ["LW", "LW"], ["RW", "RW"], ["D", "Defence"], ["G", "Goal"]])}
      ${sel("age", [["", "Any age"], [21, "21 and under"], [23, "23 and under"], [26, "26 and under"], [30, "30 and under"]])}
      ${sel("fee", [["", "Any fee"]].concat(fees.map((f) => [f, f ? `Up to ${money(f, "EUR", {short: true})}` : "Free only"])))}</div>`;
    const rows = EUC.type === "loan" ? m.filter((r) => r.loanable) : m;
    html = (d.offers.length ? panel(`Offers for your players (${d.offers.length})`, euOffers(d)) : "")
      + panel("Transfer market", filters + `<p class="muted small">${EUC.type === "loan" ? "Players their clubs would lend (outside their top lineup). You pay a share of his wage until the date you choose (at the latest 30 April); the young are lent for half, others for three quarters." :
      "Free agents cost nothing; for a player under contract his club asks a fee (about his wage times the seasons he has left, more for the young and for key players). Then he wants his wage."}${cur !== "EUR" ? ` Amounts are shown in ${cur}; offers are made in euros.` : ""}</p>`
      + table(rows, [{key: "pos", label: "Pos"}, {key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "age", label: "Age", num: true}, {key: "nat", label: "Nat"},
        {key: "overall", label: "Ability", num: true}, {key: "club", label: "Club", fmt: (r) => `${esc(r.club)}${r.league ? ` <span class="muted small">${esc(r.league)}</span>` : ""}`},
        {key: "fee", label: EUC.type === "loan" ? "His wage" : "Fee asked", num: true, fmt: (r) => EUC.type === "loan" ? eur(r.wage) : r.fee ? eur(r.fee) : '<span class="pos">free</span>'},
        {key: "ask", label: "Wants", num: true, fmt: (r) => eur(r.ask)},
        {key: "x", label: "", fmt: (r) => EUC.type === "loan"
          ? `<select class="mini" data-euloan="${r.player_id}"><option value="">Loan for...</option>${[50, 60, 75, 100].map((p) => `<option value="${p}">${p}% of his wage</option>`).join("")}</select>`
          : `<button class="mini primary" data-eubuy="${r.player_id}" data-fee="${r.fee}" data-ask="${r.ask}" data-name="${esc(r.name)}">Offer</button>`}]));
  } else {
    html = panel("Dealings", d.history.length ? table(d.history, [{key: "day", label: "Day"}, {key: "kind", label: "Kind"}, {key: "status", label: "Outcome", fmt: (r) => `<span class="${r.status === "done" || r.status === "accepted" ? "pos" : r.status === "refused" ? "neg" : ""}">${esc(r.status)}</span>`}, {key: "note", label: ""}])
      : empty("No dealings yet."));
  }
  AFTER = () => {
    document.querySelectorAll("[data-eutype]").forEach((a) => (a.onclick = () => { EUC.type = a.dataset.eutype; render(); }));
    document.querySelectorAll("[data-euf]").forEach((s) => (s.onchange = () => { EUC.f[s.dataset.euf] = s.value; if (s.dataset.euf === "fee") EUC.f.free = s.value === "0" ? "1" : ""; render(); }));
    document.querySelectorAll("[data-eubuy]").forEach((bt) => (bt.onclick = async () => {
      const free = +bt.dataset.fee === 0;
      const fee = free ? "0" : prompt(`Fee to offer for ${bt.dataset.name}, in euros (they ask ${money(bt.dataset.fee, "EUR", {native: true})})`, bt.dataset.fee);
      if (fee === null) return;
      const wage = prompt(`His wage a season, in euros (he wants ${money(bt.dataset.ask, "EUR", {native: true})})`, bt.dataset.ask);
      if (wage === null) return;
      const yrs = prompt("Seasons (1-4)", "2");
      if (yrs === null) return;
      await cmd(`club buy ${bt.dataset.eubuy} ${Math.round(+fee || 0)} ${Math.round(+wage || 0)} ${Math.max(1, Math.min(4, +yrs || 2))}`);
    }));
    document.querySelectorAll("[data-euloan]").forEach((s) => (s.onchange = () => s.value && cmd(`club loan ${s.dataset.euloan} ${s.value}%`)));
    document.querySelectorAll("[data-eulend]").forEach((s) => (s.onchange = () => s.value && cmd(`club lend ${s.dataset.eulend} #${s.value}`)));
    document.querySelectorAll("[data-eurenew]").forEach((bt) => (bt.onclick = async () => {
      const wage = prompt(`New wage a season, in euros (he wants about ${money(bt.dataset.ask, "EUR", {native: true})})`, bt.dataset.ask);
      if (wage === null) return;
      const yrs = prompt("Extra seasons (1-4)", "2");
      if (yrs === null) return;
      await cmd(`club renew ${bt.dataset.eurenew} ${Math.round(+wage || 0)} ${Math.max(1, Math.min(4, +yrs || 2))}`);
    }));
  };
  return euHead(d) + html;
}
[["dashboard", "board"], ["roster", "squad"], ["contracts", "contracts"], ["trade", "market"], ["offseason", "history"]].forEach(([v, tab]) => {
  const orig = VIEWS[v];
  VIEWS[v] = async (...a) => (STATE && STATE.eu_club ? euScreen(tab) : orig(...a));
});
// the Lineup and Tactics screens are the NHL ones; a line on what counts in the results model
["lines", "tactics"].forEach((v) => {
  const orig = VIEWS[v];
  VIEWS[v] = async (...a) => {
    const html = await orig(...a);
    if (!(STATE && STATE.eu_club)) return html;
    return `<p class="eu-note muted small">${v === "lines" ? "Your club's games are played by the full game engine, as an NHL club's: your lines, special-teams units, goalies and tactics count exactly as they do in the NHL, and every game has a recap and a 2D replay. The rest of your league is played by the quicker results model."
      : "Your tactics work as they do for an NHL club; your players' fit is measured against the clubs of your own league."}</p>` + html;
  };
});
const jobsV61 = VIEWS.jobs;
VIEWS.jobs = async (...a) => {
  let html = await jobsV61(...a);
  if (STATE && STATE.eu_club) html = html.replace(/<div class="jc-intro">[\s\S]*?<\/div>/, `<div class="jc-intro"><b>You run ${esc(STATE.eu_club.name)} (${esc(STATE.eu_club.league)}).</b> NHL clubs looking for a GM are listed here: if one hires you, you leave for the NHL and the club's AI takes over.</div>`);
  return html + panel("Manage in Europe", STATE && STATE.eu_club ? `<p><a class="btn" href="#dashboard">Your club: ${esc(STATE.eu_club.name)}</a></p>` : `<p>Prefer a club in Europe? <a class="btn" href="#euclub">European club...</a></p>`);
};
Object.assign(FR, {"European club": "Club européen", "Transfer market": "Marché des transferts", "Squad": "Effectif", "Dealings": "Transactions", "Transfer": "Transfert", "Loan": "Prêt", "Manage in Europe": "Diriger en Europe"});

/* ---- boot: moved to the last script (v61.js) ---- */
