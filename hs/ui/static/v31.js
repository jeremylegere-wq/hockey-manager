"use strict";
// v31, phase A: the depth of the screens. The schedule strip and today's event in the header, Play until a date,
// the league day by day, the transactions hub, a tabbed roster with the short list, the depth chart, the transaction
// log, milestones, reports, past drafts, season pages, rules, team info, notes, a right-click menu on players,
// column tooltips, CSV export of any table, and rolling backups (Saves menu).

/* ================================================================ small helpers */
const dshort = (iso) => { const d = new Date(String(iso).slice(0, 10) + "T12:00:00"); return isNaN(d) ? esc(iso) : d.toLocaleDateString("en-GB", {day: "numeric", month: "short"}); };
const dlong = (iso) => { const d = new Date(String(iso).slice(0, 10) + "T12:00:00"); return isNaN(d) ? esc(iso) : d.toLocaleDateString("en-GB", {weekday: "long", day: "numeric", month: "long", year: "numeric"}); };
const tabBar = (items, cur) => `<div class="tabs">${items.map(([k, l, href]) => `<a class="btn${k === cur ? " active" : ""}" href="${href}">${esc(l)}</a>`).join(" ")}</div>`;
const tm = (abbr, id) => abbr ? (id ? `<a href="#team/${id}">${crest(abbr, 14)} ${esc(abbr)}</a>` : `${crest(abbr, 14)} ${esc(abbr)}`) : '<span class="muted">-</span>';
const empty = (t) => `<p class="muted">${esc(t)}</p>`;

/* ================================================================ header: the schedule strip and today's event */
function drawStrip() {
  let el = $("#sh-strip");
  if (!el) { $("#screenhead .spacer").insertAdjacentHTML("afterend", '<div id="sh-strip" class="sh-strip"></div>'); el = $("#sh-strip"); }
  const s = STATE && STATE.started && STATE.strip;
  if (!s || !SETTINGS.schedule_strip) { el.hidden = true; return; }
  el.hidden = false;
  el.innerHTML = s.days.map((x) => {
    const d = new Date(x.date + "T12:00:00");
    const head = `<i>${d.toLocaleDateString("en-GB", {weekday: "short"})} ${d.getDate()}</i>`;
    const body = x.opp ? `${crest(x.opp, 13)}<b>${x.home ? "" : "@"}${esc(x.opp)}</b>${x.result ? `<em class="r-${x.result[0].toLowerCase()}">${esc(x.result)}</em>` : ""}` : '<span class="muted">-</span>';
    const href = x.game_id && x.result ? `#game/${x.game_id}` : `#leagueday/${x.date}`;
    return `<a class="ss-day${x.today ? " today" : ""}${x.past ? " past" : ""}" href="${href}" title="${x.opp ? (x.home ? "vs " : "at ") + esc(x.opp) : "No game"}: ${esc(x.date)}">${head}${body}</a>`;
  }).join("");
  // today's event, beside the Continue buttons (the classic Continue names the day)
  let ev = $("#sb-event");
  if (!ev) { $("#sb-controls").insertAdjacentHTML("beforebegin", '<span id="sb-event" class="sb-event"></span>'); ev = $("#sb-event"); }
  ev.textContent = s.event ? `Today: ${s.event}` : "";
  const day = document.querySelector('#sb-controls [data-sim="day"]');
  if (day) day.title = s.event ? `Continue: ${s.event} (Space)` : "Continue one day (Space)";
}
const refreshV31 = refresh;
refresh = async function () { await refreshV31(); drawStrip(); };

/* ================================================================ Play until a date or an event */
const PlayUntil = {
  async open() {
    if (!STATE || STATE.phase !== "regular_season") return toast("Play until works in the regular season; in the summer use Next offseason phase.", true);
    const t = await api("playtargets");
    const min = new Date(STATE.date + "T12:00:00"); min.setDate(min.getDate() + 1);
    const body = Modal.open(`<div class="win-title">Play Until</div><div class="pad"><p>Play on, day by day, and stop on the day you pick. Like Rest of season, it still stops for a trade offer, the owner's office and the days before the deadline.</p>
      <div class="pu-list">${t.map((x) => `<button class="pu" data-d="${x.date}"><b>${esc(x.label)}</b><span>${dlong(x.date)}</span></button>`).join("")}</div>
      <p class="row"><label>Or a date <input type="date" id="pu-date" min="${min.toISOString().slice(0, 10)}" value="${t.length ? t[0].date : min.toISOString().slice(0, 10)}"></label>
      <button class="primary" id="pu-go">Play until this date</button> <button onclick="Modal.close()">Cancel</button></p></div>`, "win");
    const go = async (date) => {
      Modal.close();
      try { await post("/api/sim", {mode: "until", until: date, pace: Sim.pace()}); } catch (e) { return toast(e.message, true); }
      Sim.attach("until");
    };
    body.querySelectorAll(".pu").forEach((b) => (b.onclick = () => go(b.dataset.d)));
    $("#pu-go").onclick = () => go($("#pu-date").value);
  },
};

/* ================================================================ the league, day by day */
VIEWS.leagueday = async (day) => {
  const d = await api("leagueday", day ? {day} : {});
  const nav = `<div class="toolbar"><a class="btn${d.prev ? "" : " disabled"}" href="${d.prev ? "#leagueday/" + d.prev : "#leagueday"}">&#9664; ${d.prev ? dshort(d.prev) : ""}</a>
    <b class="cal-name">${dlong(d.day)}</b><a class="btn${d.next ? "" : " disabled"}" href="${d.next ? "#leagueday/" + d.next : "#leagueday"}">${d.next ? dshort(d.next) : ""} &#9654;</a>
    <a class="btn" href="#leagueday/${d.today}">Today</a><span class="spacer"></span><a class="btn" href="#calendar">Your calendar</a></div>`;
  const g = d.games.length ? `<table class="ld"><thead><tr><th>Away</th><th class="num"></th><th>Home</th><th class="num"></th><th></th><th>Star of the game</th><th></th></tr></thead><tbody>${d.games.map((x) => `<tr class="${x.mine ? "mine" : ""}">
      <td>${tm(x.away, x.away_id)}</td><td class="num"><b>${x.played ? x.ag : ""}</b></td><td>${tm(x.home, x.home_id)}</td><td class="num"><b>${x.played ? x.hg : ""}</b></td>
      <td>${x.played ? `Final${x.ot ? " / " + x.ot : ""}` : x.type === "PO" ? "Playoffs" : '<span class="muted">to play</span>'}</td>
      <td>${x.star ? `${clink(x.star.player_id, x.star.name)} <span class="muted">${x.star.g}G ${x.star.a}A</span>` : ""}</td>
      <td>${x.played ? `<a href="#game/${x.game_id}">Box score &#8250;</a>` : ""}</td></tr>`).join("")}</tbody></table>` : empty("No games in the league on this day.");
  const n = d.news.length ? `<ul class="plain">${d.news.map((x) => `<li><a href="#article/${x.event_id}">${esc(x.text)}</a></li>`).join("")}</ul>` : empty("No news.");
  return nav + `<div class="grid two">${panel(`Games (${d.games.length})`, g)}${panel("Around the league", n)}</div>`;
};

/* ================================================================ transactions hub */
const HUB = [["offseason", "Offseason"], ["free", "Free agents"], ["upcoming", "Upcoming free agents"], ["block", "Trade block"], ["waivers", "Waivers"],
  ["sheets", "Offer sheets"], ["injured", "Injured"], ["shortlist", "Short list"], ["log", "Transaction log"]];
const TH = {team: ""};
VIEWS.transactions = async (tab = "free") => {
  if (tab === "offseason") { location.hash = "#offseason"; return ""; }
  if (tab === "log") { location.hash = "#txnlog"; return ""; }
  const d = await api("transactions", Object.assign({tab}, TH.team ? {team: TH.team} : {}));
  const bar = tabBar(HUB.map(([k, l]) => [k, l, k === "offseason" ? "#offseason" : k === "log" ? "#txnlog" : `#transactions/${k}`]), d.tab);
  const pick = d.tab === "free" ? "" : `<div class="toolbar"><label>Club <select id="th-team"><option value="">The whole league</option>${(d.clubs || []).map((c) =>
    `<option value="${c.team_id}"${+TH.team === c.team_id ? " selected" : ""}>${esc(c.abbr)}</option>`).join("")}</select></label><span class="spacer"></span><span class="muted">${d.rows.length} rows</span></div>`;
  const prev = AFTER;
  AFTER = async () => { if (prev) await prev(); const s = $("#th-team"); if (s) s.onchange = () => { TH.team = s.value; render(); }; };
  return bar + pick + hubPanel(d);
};
function hubPanel(d, title = null) {
  const P = {key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, POS = {key: "pos", label: "Pos"}, AGE = {key: "age", label: "Age", num: true};
  const VAL = {key: "value", label: "Value", num: true}, TEAM = {key: "team", label: "Club", fmt: (r) => tm(r.team, r.team_id)};
  const cols = {
    free: [P, POS, AGE, VAL, {key: "ask", label: "Asking", num: true, fmt: (r) => mil(r.ask)}, {key: "x", label: "", fmt: (r) => `<button class="mini" data-cmd="sign ${r.player_id}" data-confirm="Sign ${esc(r.name)} at his ask (${mil(r.ask)})?">Sign at ask</button>`}],
    upcoming: [P, POS, AGE, TEAM, VAL, {key: "cap_hit", label: "Cap hit", num: true, fmt: (r) => mil(r.cap_hit)}, {key: "status", label: "At expiry"}],
    block: [P, POS, AGE, TEAM, VAL, {key: "cap_hit", label: "Cap hit", num: true, fmt: (r) => mil(r.cap_hit)}, {key: "since", label: "On the block since"},
      {key: "x", label: "", fmt: (r) => r.team_id && STATE && r.team_id !== STATE.team_id ? `<a class="btn mini" href="#trade/${r.team_id}">Make an offer</a>` : ""}],
    waivers: [P, POS, AGE, {key: "team", label: "Placed by", fmt: (r) => tm(r.team)}, {key: "placed", label: "Placed"}, {key: "clears", label: "Clears"},
      {key: "outcome", label: "Outcome", fmt: (r) => r.open ? '<span class="tag warn">on waivers</span>' : esc(r.outcome) + (r.claimed_by ? ` by ${esc(r.claimed_by)}` : "")}],
    sheets: [P, POS, {key: "offering", label: "Offer from", fmt: (r) => tm(r.offering)}, {key: "holding", label: "Rights held by", fmt: (r) => tm(r.holding)},
      {key: "aav", label: "AAV", num: true, fmt: (r) => mil(r.aav)}, {key: "years", label: "Years", num: true}, {key: "made_on", label: "Made"}, {key: "status", label: "Outcome"}],
    injured: [P, POS, TEAM, {key: "injury", label: "Injury"}, {key: "since", label: "Since"}, {key: "back", label: "Expected back"},
      {key: "days", label: "Days", num: true}, {key: "ltir", label: "", fmt: (r) => r.ltir ? '<span class="tag neg">LTIR</span>' : ""}],
    shortlist: [P, POS, AGE, {key: "team", label: "Club", fmt: (r) => r.team_id ? tm(r.team, r.team_id) : esc(r.team)}, VAL,
      {key: "cap_hit", label: "Cap hit", num: true, fmt: (r) => mil(r.cap_hit)}, {key: "ends", label: "Final season", fmt: (r) => ssn(r.ends)},
      {key: "added", label: "Added"}, {key: "reason", label: "Why"}, {key: "x", label: "", fmt: (r) => `<button class="mini" data-cmd="shortlist del ${r.player_id}">Remove</button>`}],
  }[d.tab];
  const titles = {free: "Free agents", upcoming: "Contracts ending this season", block: "Players on the trade block", waivers: "Waiver wire and recent waivers",
    sheets: "Offer sheets", injured: "Injured around the league", shortlist: "Your short list"};
  const none = {free: "Nobody is unsigned right now. The market fills on 1 July.", upcoming: "No contracts end this season.", block: "Nobody is on the block.",
    waivers: "Nobody has been on waivers this season.", sheets: "No offer sheets yet.", injured: "Nobody is hurt.", shortlist: "Your short list is empty: right-click a player (or use Add to short list on his profile)."}[d.tab];
  return panel(`${title || titles[d.tab]} (${d.rows.length})`, d.rows.length ? `<div class="scroll tall">${table(d.rows, cols, {rowClass: (r) => STATE && r.team_id === STATE.team_id ? "mine" : ""})}</div>` : empty(none));
}

/* ================================================================ roster tabs */
const rosterV31 = VIEWS.roster;
VIEWS.roster = async (arg) => {
  const cur = arg === "system" ? "system" : arg === "shortlist" ? "shortlist" : arg === "injured" ? "injured" : "nhl";
  const bar = tabBar([["nhl", "NHL roster", "#roster"], ["system", "Whole organisation", "#roster/system"], ["depth", "Depth chart", "#depth"],
    ["rights", "Draft rights", "#prospects"], ["contracts", "Contracts", "#contracts"], ["injured", "Injured", "#roster/injured"], ["shortlist", "Short list", "#roster/shortlist"]], cur);
  if (cur === "shortlist" || cur === "injured") {
    const d = await api("transactions", {tab: cur});
    if (cur === "injured") d.rows = d.rows.filter((r) => STATE && r.team_id === STATE.team_id);
    return bar + hubPanel(d, cur === "injured" ? "Your injured players" : null) + (cur === "injured" ? '<p class="muted small">The whole league: League &gt; Injury Report.</p>' : "");
  }
  const html = await rosterV31(arg);
  return bar + html.replace(/^<div class="tabs">[\s\S]*?<\/div>/, "");
};

/* ================================================================ depth chart */
VIEWS.depth = async (team) => {
  const d = await api("depth", team ? {team} : {});
  const lvl = {NHL: "", Minors: "minors", Rights: "rights"};
  const col = (pos, title) => `<div class="dc-col"><h3>${title} <span class="muted">${d.columns[pos].length}</span></h3>${d.columns[pos].map((p) => `<div class="dc-p ${lvl[p.level]}">
      <div>${clink(p.player_id, p.name)} <span class="muted">${p.age}</span></div>
      <div class="small">${p.level === "NHL" ? `<b>${p.value}</b>` : `<span class="tag">${esc(p.level === "Rights" ? "rights" : "minors")}</span> ${p.value}`}
        ${p.potential != null ? ` · pot ${potentialStars(p.potential)}` : ""}${p.cap_hit ? ` · ${mil(p.cap_hit)} to ${ssn(p.ends)}` : ""}</div>
      ${p.club ? `<div class="small muted">${esc(p.club)}</div>` : ""}</div>`).join("") || empty("Nobody.")}</div>`;
  const picks = d.picks.length ? `<ul class="plain cols">${d.picks.map((p) => `<li>${esc(p.label)}</li>`).join("")}</ul>` : empty("No tradeable picks.");
  const head = `<div class="toolbar">${crest(d.abbr, 22)} <b>${esc(d.name)}</b><span class="spacer"></span><span class="muted small">NHL, then the minors, then unsigned rights; best first in each</span>
    ${STATE && d.team_id !== STATE.team_id ? `<a class="btn" href="#depth">Your club</a>` : ""}<a class="btn" href="#team/${d.team_id}">Team page</a></div>`;
  return (STATE && d.team_id === STATE.team_id ? tabBar([["nhl", "NHL roster", "#roster"], ["system", "Whole organisation", "#roster/system"], ["depth", "Depth chart", "#depth"],
    ["rights", "Draft rights", "#prospects"], ["contracts", "Contracts", "#contracts"], ["injured", "Injured", "#roster/injured"], ["shortlist", "Short list", "#roster/shortlist"]], "depth") : "")
    + head + panel("Depth chart", `<div class="depth">${col("G", "Goal")}${col("D", "Defence")}${col("LW", "Left wing")}${col("C", "Centre")}${col("RW", "Right wing")}</div>`)
    + (d.pick_grid ? panel("Draft picks", pickGrid(d.pick_grid)) : panel("Future draft picks", picks));
};

// v38 (#7): picks draft by draft, round by round
const pickGrid = (rows) => rows.length ? `<table class="pgrid"><thead><tr><th>Draft</th>${[1, 2, 3, 4, 5, 6, 7].map((r) => `<th>${ordinal(r)}</th>`).join("")}</tr></thead><tbody>${rows.map((y) =>
  `<tr><th>${y.year}</th>${y.cells.map((c) => `<td class="${c.own ? "own" : "gone"}${c.extra.length ? " plus" : ""}">${c.own ? '<span class="pk own">Own</span>' : `<span class="pk gone" title="Traded away">to ${esc(c.to)}</span>`}${c.extra.map((x) => `<span class="pk got" title="Acquired">${esc(x)}</span>`).join("")}${c.swap ? '<span class="pk sw">swap</span>' : ""}</td>`).join("")}</tr>`).join("")}</tbody></table>
  <p class="muted small"><span class="pk own">Own</span> your own pick · <span class="pk gone">to XXX</span> traded away · <span class="pk got">XXX</span> acquired from that club</p>` : empty("No future drafts open for trading.");

/* ================================================================ transaction log */
const TL = {season: null, team: "all", kind: "", minor: false};
VIEWS.txnlog = async () => {
  const d = await api("txnlog", {season: TL.season || "", team: TL.team, kind: TL.kind, minor: TL.minor ? "1" : ""});
  TL.season = d.season;
  const bar = tabBar(HUB.map(([k, l]) => [k, l, k === "offseason" ? "#offseason" : k === "log" ? "#txnlog" : `#transactions/${k}`]), "log");
  const ctl = `<div class="toolbar"><label>Season <select id="tl-s">${d.seasons.map((s) => `<option value="${s}"${s === d.season ? " selected" : ""}>${ssn(s)}</option>`).join("")}</select></label>
    <label>Club <select id="tl-t"><option value="all">The league</option><option value="mine"${TL.team === "mine" ? " selected" : ""}>Your club</option></select></label>
    <label>Kind <select id="tl-k"><option value="">Everything</option>${d.kinds.map((k) => `<option value="${k}"${k === d.kind ? " selected" : ""}>${esc(d.kind_labels[k])}</option>`).join("")}</select></label>
    <label><input type="checkbox" id="tl-m"${TL.minor ? " checked" : ""}> Minor-league and European moves</label><span class="spacer"></span><span class="muted">${d.rows.length} entries</span></div>`;
  AFTER = () => {
    $("#tl-s").onchange = (e) => { TL.season = +e.target.value; render(); };
    $("#tl-t").onchange = (e) => { TL.team = e.target.value; render(); };
    $("#tl-k").onchange = (e) => { TL.kind = e.target.value; render(); };
    $("#tl-m").onchange = (e) => { TL.minor = e.target.checked; render(); };
  };
  const t = table(d.rows, [{key: "date", label: "Date"}, {key: "label", label: "Kind"}, {key: "name", label: "Player", fmt: (r) => r.player_id ? clink(r.player_id, r.name) : ""},
    {key: "pos", label: "Pos"}, {key: "frm", label: "From", fmt: (r) => r.frm ? tm(r.frm) : ""}, {key: "to", label: "To", fmt: (r) => r.to ? tm(r.to) : ""}, {key: "detail", label: "Detail"}]);
  return bar + ctl + panel(`Transactions ${ssn(d.season)}`, d.rows.length ? `<div class="scroll tall">${t}</div>` : empty("Nothing recorded."));
};

/* ================================================================ milestones */
VIEWS.milestones = async () => {
  const d = await api("milestones");
  const near = table(d.near, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "team", label: "Club", fmt: (r) => tm(r.team)},
    {key: "mark", label: "Milestone", fmt: (r) => `<b>${r.mark}</b> ${esc(r.stat)}`}, {key: "total", label: "Now", num: true}, {key: "to_go", label: "To go", num: true}]);
  const got = table(d.reached, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "team", label: "Club", fmt: (r) => tm(r.team)},
    {key: "mark", label: "Reached", fmt: (r) => `<b>${r.mark}</b> ${esc(r.stat)}`}, {key: "total", label: "Now", num: true}]);
  return `<div class="grid two">${panel("Coming up", d.near.length ? `<div class="scroll tall">${near}</div>` : empty("Nobody is close to a milestone."))}
    ${panel("Reached this season", d.reached.length ? `<div class="scroll tall">${got}</div>` : empty("None yet this season."))}</div>
    <p class="muted small">Career regular-season totals in the top league (games, goals, assists and points for skaters; games, wins and shutouts for goalies).</p>`;
};

/* ================================================================ reports */
const REP = [["positional", "Positional rankings"], ["prospects", "Prospect rankings"], ["injuries", "Injury report"], ["performances", "Game performances"], ["morale", "Morale report"], ["power", "Power rankings"]];
VIEWS.reports = async (kind = "positional") => {
  if (kind === "power") { location.hash = "#news/power"; return ""; }
  const d = await api("reports", {kind});
  const tabs = tabBar(REP.map(([k, l]) => [k, l, k === "power" ? "#news/power" : `#reports/${k}`]), d.kind);
  const P = {key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)};
  let body = "";
  if (d.kind === "positional") {
    const names = {C: "Centres", LW: "Left wings", RW: "Right wings", D: "Defencemen", G: "Goalies"};
    body = `<div class="grid three">${["C", "LW", "RW", "D", "G"].filter((k) => d.groups[k]).map((k) => panel(`${names[k]}${d.mine[k] ? ` · your best is #${d.mine[k]}` : ""}`,
      table(d.groups[k].map((r, i) => ({...r, rank: i + 1})), [{key: "rank", label: "#", num: true}, P, {key: "team", label: "Club", fmt: (r) => tm(r.team, r.team_id)},
        {key: "age", label: "Age", num: true}, {key: "value", label: "Value", num: true}], {rowClass: (r) => STATE && r.team_id === STATE.team_id ? "mine" : ""}))).join("")}</div>`;
  } else if (d.kind === "prospects") {
    body = panel("The league's best young players (21 and under)", `<div class="scroll tall">${table(d.rows, [{key: "rank", label: "#", num: true}, P, {key: "pos", label: "Pos"},
      {key: "age", label: "Age", num: true}, {key: "owner", label: "Rights", fmt: (r) => tm(r.owner, r.team_id)}, {key: "club", label: "Playing", fmt: (r) => r.nhl ? "NHL" : esc(r.club || "")},
      {key: "value", label: "Ability", fmt: (r) => `${abilityStars(r.value)} <span class="muted small">${r.value}</span>`}, {key: "potential", label: "Potential", fmt: (r) => potentialStars(r.potential)}],
      {rowClass: (r) => STATE && r.team_id === STATE.team_id ? "mine" : ""})}</div><p class="muted small">Ranked on potential first, then ability; your scouts' view, not the truth.</p>`);
  } else if (d.kind === "injuries") {
    body = panel(`Injury report (${d.rows.length})`, d.rows.length ? table(d.rows, [P, {key: "pos", label: "Pos"}, {key: "team", label: "Club", fmt: (r) => tm(r.team, r.team_id)},
      {key: "injury", label: "Injury"}, {key: "since", label: "Since"}, {key: "back", label: "Expected back"}, {key: "days", label: "Days", num: true}], {rowClass: (r) => STATE && r.team_id === STATE.team_id ? "mine" : ""}) : empty("Nobody is hurt."));
  } else if (d.kind === "performances") {
    const g = (r) => `<a href="#game/${r.game_id}">${dshort(r.date)}</a>`;
    body = `<div class="grid two">${panel("Best skater games this season", d.skaters.length ? table(d.skaters, [{key: "date", label: "Date", fmt: g}, P, {key: "team", label: "Club", fmt: (r) => tm(r.team)},
      {key: "opp", label: "Against", fmt: (r) => tm(r.opp)}, {key: "g", label: "G", num: true}, {key: "a", label: "A", num: true}, {key: "pts", label: "P", num: true}, {key: "sog", label: "SOG", num: true}]) : empty("No games yet this season."))}
      ${panel("Best goalie games (20+ shots)", d.goalies.length ? table(d.goalies, [{key: "date", label: "Date", fmt: g}, P, {key: "team", label: "Club", fmt: (r) => tm(r.team)},
      {key: "opp", label: "Against", fmt: (r) => tm(r.opp)}, {key: "sv", label: "Saves", num: true}, {key: "sa", label: "Shots", num: true}, {key: "pct", label: "SV%", num: true, fmt: (r) => f3(r.pct)}]) : empty("No games yet this season."))}</div>`;
  } else if (d.kind === "morale") {
    const b = (v) => bar(v);
    body = (d.room ? `<div class="toolbar"><span>Room cohesion <b>${d.room.cohesion}</b></span><span>Leadership <b>${d.room.leadership}</b></span><span>Atmosphere <b>${esc(d.room.atmosphere)}</b></span></div>` : "")
      + panel("Your players, unhappiest first", table(d.rows, [P, {key: "pos", label: "Pos"}, {key: "morale", label: "Morale", fmt: (r) => b(r.morale)}, {key: "role", label: "Role", num: true},
        {key: "team", label: "Team", num: true}, {key: "contract", label: "Contract", num: true}, {key: "trust_mgmt", label: "Trust in you", num: true}, {key: "trust_coach", label: "Trust in coach", num: true},
        {key: "trade_request", label: "", fmt: (r) => r.trade_request ? '<span class="tag neg">wants a trade</span>' : ""}]));
  }
  return tabs + body;
};

/* ================================================================ past drafts */
VIEWS.draftlog = async (year) => {
  const d = await api("draftlog", year ? {year} : {});
  if (!d.year) return panel("Past drafts", empty("No draft has been held yet in this career. The first is in June. (Past drafts from before the save can be imported: File > Editor > Import / Export.)"));
  const ctl = `<div class="toolbar"><label>Draft <select id="dl-y">${d.years.map((y) => `<option${y === d.year ? " selected" : ""}>${y}</option>`).join("")}</select></label>
    <span class="spacer"></span><a class="btn" href="#draft">Draft room</a></div>`;
  AFTER = () => { $("#dl-y").onchange = (e) => { location.hash = `#draftlog/${e.target.value}`; }; };
  const t = table(d.rows, [{key: "overall", label: "#", num: true}, {key: "round", label: "Rd", num: true}, {key: "team", label: "Club", fmt: (r) => tm(r.team) + (r.note ? ` <span class="muted small">${esc(r.note)}</span>` : "")},
    {key: "name", label: "Player", fmt: (r) => r.player_id ? clink(r.player_id, r.name) : `<span class="muted">${esc(r.name)}</span>`}, {key: "pos", label: "Pos"}, {key: "nat", label: "Nat"}, {key: "now", label: "Now"},
    {key: "nhl_gp", label: "NHL GP", num: true}, {key: "value", label: "Value now", num: true}], {rowClass: (r) => r.mine ? "mine" : ""});
  return ctl + panel(`${d.year} entry draft (${d.rows.length} picks)`, `<div class="scroll tall">${t}</div>`);
};

/* ================================================================ league history: season pages */
VIEWS.season = async (year) => {
  const d = await api("season", year ? {year} : {});
  if (!d.year) return panel("Season pages", empty("A season page appears when the first season is over."));
  const ctl = `<div class="toolbar"><label>Season <select id="sp-y">${d.years.map((y) => `<option value="${y}"${y === d.year ? " selected" : ""}>${ssn(y)}</option>`).join("")}</select></label>
    <span class="spacer"></span><a class="btn" href="#champions/${d.year}">Champions</a> <a class="btn" href="#awards/${d.year}">Awards night</a> <a class="btn" href="#draftlog/${d.year + 1}">Draft ${d.year + 1}</a> <a class="btn" href="#stats/history">Records</a></div>`;
  AFTER = () => { $("#sp-y").onchange = (e) => { location.hash = `#season/${e.target.value}`; }; };
  const champ = d.champion ? `<div class="sp-champ">${crest(d.champion.abbr, 54)}<div><i>Stanley Cup champions</i><b>${esc(d.champion.name)}</b><span>${d.champion.w}-${d.champion.l}-${d.champion.otl}, ${d.champion.pts} points</span></div></div>` : "";
  const st = table(d.standings.map((r, i) => ({...r, rank: i + 1})), [{key: "rank", label: "#", num: true}, {key: "abbr", label: "Club", fmt: (r) => tlink(r.team_id, r.name, d.year)},
    {key: "conf", label: "Conf"}, {key: "gp", label: "GP", num: true}, {key: "w", label: "W", num: true}, {key: "l", label: "L", num: true}, {key: "otl", label: "OTL", num: true},
    {key: "pts", label: "PTS", num: true}, {key: "gf", label: "GF", num: true}, {key: "ga", label: "GA", num: true}, {key: "playoffs", label: "Playoffs"}], {rowClass: (r) => STATE && r.team_id === STATE.team_id ? "mine" : ""});
  const aw = d.awards.length ? `<ul class="plain">${d.awards.map((a) => `<li><b>${esc(a.award.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()))}</b>: ${a.player_id ? clink(a.player_id, a.name) : esc(a.name)} ${a.team ? tm(a.team) : ""} <span class="muted small">${esc(a.detail || "")}</span></li>`).join("")}</ul>` : empty("No awards recorded.");
  const sc = table(d.scorers, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "team", label: "Club", fmt: (r) => tm(r.team)}, {key: "gp", label: "GP", num: true},
    {key: "g", label: "G", num: true}, {key: "a", label: "A", num: true}, {key: "pts", label: "P", num: true}]);
  const gk = table(d.goalies, [{key: "name", label: "Goalie", fmt: (r) => clink(r.player_id, r.name)}, {key: "team", label: "Club", fmt: (r) => tm(r.team)}, {key: "gp", label: "GP", num: true},
    {key: "w", label: "W", num: true}, {key: "sv", label: "SV%", num: true, fmt: (r) => f3(r.sv)}, {key: "gaa", label: "GAA", num: true, fmt: (r) => f2(r.gaa)}, {key: "so", label: "SO", num: true}]);
  return ctl + champ + `<div class="grid two">${panel(`Final standings ${ssn(d.year)}`, st)}<div>${panel("Awards", aw)}${panel("Scoring leaders", sc)}${panel("Goaltending", gk)}</div></div>`;
};

/* ================================================================ rules */
VIEWS.rules = async () => {
  const d = await api("rules");
  const kv = (rows) => `<table class="kvt">${rows.map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join("")}</table>`;
  return `<div class="grid two">${panel("Season format", `<p><b>This season</b> ${esc(d.this)}</p><p><b>Next season</b> ${esc(d.next)}</p><p class="muted">Rule era preset: ${esc(d.era)}. Console: <code>rules preset nhl|off</code>.</p>`)}
    ${panel("Rosters", kv(d.roster))}${panel("Salary cap and contracts", kv(d.cap))}</div>`;
};

/* ================================================================ team info */
VIEWS.teaminfo = async (id) => {
  const d = await api("teaminfo", {id: id || (STATE && STATE.team_id)});
  const kv = (rows) => `<table class="kvt">${rows.filter((r) => r[1] != null && r[1] !== "").map(([k, v]) => `<tr><th>${esc(k)}</th><td>${v}</td></tr>`).join("")}</table>`;
  const club = kv([["League", esc(d.league)], ["Conference", esc(d.conference)], ["Division", esc(d.division)],
    ["Affiliates", d.affiliates.map((a) => `<a href="#team/${a.team_id}">${esc(a.name)}</a> <span class="muted">${esc(a.league)}</span>`).join("<br>") || "none"],
    ["Parent club", d.parent ? `<a href="#team/${d.parent.team_id}">${esc(d.parent.name)}</a>` : ""],
    ["Payroll", d.cap ? `${mil(d.cap.payroll)} (room ${mil(d.cap.room)} under ${mil(d.cap.ceiling)})` : ""],
    ["Retired numbers", d.numbers.length ? d.numbers.join(", ") : '<span class="muted">not in the data yet</span>']]);
  const people = kv([["Owner", d.owner ? `${esc(d.owner.name)} <span class="muted">${esc(d.owner.archetype || "")}</span>` : ""],
    ["General manager", d.gm ? `${esc(d.gm.name || "")}${d.gm.since ? ` <span class="muted">since ${esc(d.gm.since)}</span>` : ""}` : ""],
    ...d.staff.map((s) => [s.role, `${esc(s.name)} <span class="muted">${s.age || ""}</span>`]),
    ["Captain", d.leaders.filter((l) => l.role === "C").map((l) => clink(l.player_id, l.name)).join("") || "none"],
    ["Alternates", d.leaders.filter((l) => l.role === "A").map((l) => clink(l.player_id, l.name)).join(", ") || "none"]]);
  const mood = kv([["Room cohesion", d.room ? bar(d.room.cohesion) : ""], ["Atmosphere", d.room ? esc(d.room.atmosphere) : ""],
    ["Fans", d.mood ? bar(d.mood.fans) : ""], ["Media", d.mood ? bar(d.mood.media) : ""],
    ["Controversy", d.mood ? bar(d.mood.controversy) : ""], ["Job security", d.job ? `${esc(d.job.label)} (${d.job.confidence})` : ""]]);
  return `<div class="toolbar">${crest(d.abbr, 30)} <b class="ti-name">${esc(d.name)}</b><span class="spacer"></span><a class="btn" href="#team/${d.team_id}">Team page</a> <a class="btn" href="#depth/${d.team_id}">Depth chart</a></div>
    <div class="grid three">${panel("The club", club)}${panel("People", people)}${panel("Mood", mood)}</div>`;
};

/* ================================================================ notes and the short list */
VIEWS.notes = async () => {
  const d = await api("notes");
  const list = d.notes.length ? d.notes.map((n) => `<div class="note"><div class="note-h"><b>${dshort(n.created)}</b>${n.player ? ` · ${clink(n.player_id, n.player)}` : ""}${n.team ? ` · ${tm(n.team, n.team_id)}` : ""}
      <span class="spacer"></span><button class="mini" data-edit="${n.note_id}">Edit</button> <button class="mini" data-cmd="note del ${n.note_id}" data-confirm="Delete this note?">Delete</button></div>
      <div class="note-b" id="nb-${n.note_id}">${mailBody(n.text)}</div></div>`).join("") : empty("No notes yet.");
  AFTER = () => {
    $("#nt-add").onclick = async () => { const t = $("#nt-text").value.trim(); if (!t) return; await cmd(`note add ${t.replace(/\n/g, " / ")}`); };
    document.querySelectorAll("[data-edit]").forEach((b) => (b.onclick = async () => {
      const n = d.notes.find((x) => x.note_id === +b.dataset.edit);
      const t = await ask("Edit the note", {input: n.text, ok: "Save"});
      if (t != null && t.trim()) cmd(`note edit ${n.note_id} ${t.replace(/\n/g, " / ")}`);
    }));
  };
  return `<div class="grid two">${panel("Notebook", `<div class="nt-new"><textarea id="nt-text" rows="3" placeholder="A note for yourself: a player to watch, a promise, a plan for the deadline..."></textarea>
      <button class="primary" id="nt-add">Add note</button></div>${list}`)}
    ${panel(`Short list (${d.shortlist.length})`, d.shortlist.length ? table(d.shortlist, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "pos", label: "Pos"},
      {key: "team", label: "Club", fmt: (r) => r.team_id ? tm(r.team, r.team_id) : esc(r.team)}, {key: "value", label: "Value", num: true},
      {key: "x", label: "", fmt: (r) => `<button class="mini" data-cmd="shortlist del ${r.player_id}">Remove</button>`}]) : empty("Right-click any player to add him."), '<a href="#roster/shortlist">Full list &#8250;</a>')}</div>`;
};

/* ================================================================ the player screen: short list and notes */
const playerV31 = VIEWS.player;
VIEWS.player = async (id) => {
  const html = await playerV31(id);
  const prev = AFTER;
  AFTER = async () => {
    if (prev) prev();
    const m = await api("playermarks", {id}).catch(() => null);
    if (!m) return;
    const hero = $(".pp-id");
    if (!hero) return;
    hero.insertAdjacentHTML("beforeend", `<div class="pp-marks">${m.shortlisted ? `<button class="mini" data-cmd="shortlist del ${id}">&#9733; On your short list</button>`
      : `<button class="mini" data-cmd="shortlist add ${id}">&#9734; Add to short list</button>`} <button class="mini" id="pp-note">Add note</button>
      ${m.notes.length ? `<span class="muted small">${m.notes.length} note${m.notes.length > 1 ? "s" : ""}: ${esc(m.notes[0].text.slice(0, 80))}</span>` : ""}</div>`);
    $("#pp-note").onclick = async () => { const t = await ask("A note about this player", {input: "", ok: "Save"}); if (t && t.trim()) cmd(`note about ${id} ${t.replace(/\n/g, " / ")}`); };
  };
  return html;
};

/* ================================================================ right-click menu on players */
const Ctx = {
  close() { const m = $("#ctx"); if (m) m.remove(); },
  async open(x, y, pid, name) {
    this.close();
    const m = await api("playermarks", {id: pid}).catch(() => ({shortlisted: false, notes: []}));
    const items = [["View profile", () => { location.hash = `#player/${pid}`; }], ["Contract", () => { location.hash = `#player/${pid}/contract`; }],
      ["Career stats", () => { location.hash = `#player/${pid}/stats`; }], "-",
      m.shortlisted ? ["Remove from short list", () => cmd(`shortlist del ${pid}`)] : ["Add to short list", () => cmd(`shortlist add ${pid}`)],
      ["Add note...", async () => { const t = await ask(`A note about ${name}`, {input: "", ok: "Save"}); if (t && t.trim()) cmd(`note about ${pid} ${t.replace(/\n/g, " / ")}`); }], "-",
      ["Trade for him...", async () => {
        const p = await api("player", {id: pid}).catch(() => null);
        if (p && p.team_id && !p.mine) { TRADE_WANT = pid; location.hash = `#trade/${p.team_id}`; }
        else { location.hash = `#trade`; toast(`Pick his club on the Trade screen and add ${name}.`); }
      }]];
    document.body.insertAdjacentHTML("beforeend", `<div id="ctx" class="ctx" style="left:${x}px;top:${y}px"><div class="ctx-h">${esc(name)}</div>${items.map((it, i) => it === "-" ? '<div class="mb-sep"></div>' : `<button data-ci="${i}">${esc(it[0])}</button>`).join("")}</div>`);
    const el = $("#ctx");
    const r = el.getBoundingClientRect();
    if (r.right > innerWidth) el.style.left = (innerWidth - r.width - 4) + "px";
    if (r.bottom > innerHeight) el.style.top = (innerHeight - r.height - 4) + "px";
    el.querySelectorAll("button").forEach((b) => (b.onclick = () => { this.close(); items[+b.dataset.ci][1](); }));
  },
};
document.addEventListener("contextmenu", (e) => {
  const a = e.target.closest('a[href^="#player/"]');
  if (!a) return;
  e.preventDefault();
  Ctx.open(e.clientX, e.clientY, +a.getAttribute("href").split("/")[1], a.textContent.trim());
});
document.addEventListener("click", (e) => { if (!e.target.closest("#ctx")) Ctx.close(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") Ctx.close(); });

/* ================================================================ column tooltips and CSV export */
const TIPS = {GP: "Games played", G: "Goals", A: "Assists", P: "Points", PTS: "Points", PIM: "Penalty minutes", "+/-": "Plus-minus", SOG: "Shots on goal", TOI: "Time on ice a game",
  "SV%": "Save percentage", GAA: "Goals against average", SO: "Shutouts", W: "Wins", L: "Losses", OTL: "Overtime losses", GF: "Goals for", GA: "Goals against",
  Val: "Value: the scouts' overall rating (age-adjusted)", Value: "Value: the scouts' overall rating (age-adjusted)", Pos: "Position", Nat: "Nationality",
  "CF%": "Corsi for %: share of shot attempts at even strength", "xG": "Expected goals", "xGF%": "Expected goals share", "PP%": "Power-play %", "PK%": "Penalty-kill %",
  "Rd": "Draft round", AAV: "Average annual value (the cap hit)", "Cap hit": "Average annual value counted against the cap", "G-A": "Goals - assists", "NHL GP": "Games in the top league",
  OFF: "Offensive awareness", PAS: "Passing", PCK: "Puck control", SHT: "Shot accuracy", POS: "Positioning", DEF: "Defensive awareness", HIT: "Hitting", SPD: "Speed"};
const decorateV31 = decorate;
decorate = function (root) {
  decorateV31(root);
  if (!root) return;
  root.querySelectorAll("th:not([title])").forEach((th) => { const t = TIPS[th.textContent.trim()]; if (t) th.title = t; });
  const noCsv = /^#trade/.test(location.hash);          // v42 (register v39 #4): not on the trade screens
  root.querySelectorAll("section.panel").forEach((p) => {
    const h = p.querySelector(":scope > h2"), t = p.querySelector("table:not(.kvt):not(.calendar)");
    if (noCsv) return;
    if (!h || !t || h.querySelector(".csv")) return;
    h.insertAdjacentHTML("beforeend", '<button class="csv" title="Export this table to a CSV file">CSV</button>');
  });
};
document.addEventListener("click", async (e) => {
  const b = e.target.closest("button.csv");
  if (!b) return;
  const p = b.closest("section.panel"), t = p.querySelector("table:not(.kvt):not(.calendar)"), name = (p.querySelector("h2").firstChild.textContent || "table").trim();
  const rows = [...t.rows].map((r) => [...r.cells].map((c) => c.textContent.replace(/\s+/g, " ").trim()));
  try {
    const r = await post("/api/export", {name, rows});
    toast(`Exported ${r.rows} rows to ${r.path}`);
  } catch (err) { return toast(err.message, true); }
  if (!APP.desktop) {                                   // in a browser tab, download it as well
    const csv = rows.map((r) => r.map((v) => /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v).join(",")).join("\n");
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csv], {type: "text/csv"})); a.download = name.replace(/[^\w -]/g, "") + ".csv"; a.click();
  }
});

/* ================================================================ rolling backups (Saves menu) */
const Backups = {
  async open() {
    const d = await post("/api/save", {action: "backups"}).catch((e) => { toast(e.message, true); return null; });
    if (!d) return;
    const rows = d.backups.length ? `<table><thead><tr><th>Backup</th><th>Made</th><th class="num">Size</th><th></th></tr></thead><tbody>${d.backups.map((b) => `<tr><td>${esc(b.label)}</td>
      <td>${new Date(b.modified * 1000).toLocaleString("en-GB")}</td><td class="num">${(b.size / 1048576).toFixed(1)} MB</td><td><button class="mini" data-f="${esc(b.file)}">Restore as a new save</button></td></tr>`).join("")}</tbody></table>`
      : empty("No backups yet. One is made each game week and at every new phase.");
    const body = Modal.open(`<div class="win-title">Backups: ${esc(d.career || "")}</div><div class="pad"><p class="muted">Rolling backups of this career (Settings: how many to keep, 0 for none). Restoring makes a new save; this one is left alone.</p>
      ${rows}<p class="row right"><button id="bk-now">Back up now</button> <button onclick="Modal.close()">Close</button></p></div>`, "win wide");
    $("#bk-now").onclick = async () => { const r = await post("/api/save", {action: "backup"}).catch((e) => toast(e.message, true)); if (r) { toast(r.output); this.open(); } };
    body.querySelectorAll("[data-f]").forEach((b) => (b.onclick = async () => {
      const name = await ask("Name for the restored save", {input: `${d.career} restored`, ok: "Restore"});
      if (!name) return;
      try { const r = await post("/api/save", {action: "restore", career: d.career, file: b.dataset.f, name}); Modal.close(); toast(r.output); refresh(); }
      catch (e) { toast(e.message, true); }
    }));
  },
};

/* ================================================================ menus, names, the top tabs */
(() => {
  const find = (name) => MENUS.find((m) => m[0] === name)[1];
  const at = (list, label) => list.findIndex((it) => it !== "-" && it[0] === label);
  const mgr = find("Manager"); mgr.splice(at(mgr, "Press Room") + 1, 0, ["Notes", "#notes"], ["Short List", "#roster/shortlist"]);
  const team = find("Team");
  team.splice(at(team, "Roster") + 1, 0, ["Depth Chart", "#depth"]);
  team.splice(at(team, "Team Page") + 1, 0, ["Team Info", () => { location.hash = `#teaminfo/${STATE.team_id}`; }]);
  const lg = find("League");
  lg.splice(at(lg, "Free Agent Centre"), 2, ["Transactions", "#transactions"], ["Free Agent Centre", "#freeagents"], ["Transaction Log", "#txnlog"], ["Offseason", "#offseason"]);
  lg.splice(at(lg, "News"), 0, ["Schedule by Day", "#leagueday"], ["Injury Report", "#reports/injuries"], "-");
  lg.push(["Season Pages", "#season"], ["Past Drafts", "#draftlog"], ["Rules", "#rules"]);
  const st = find("Statistics");
  st.splice(at(st, "Advanced Analytics"), 0, ["Milestones", "#milestones"], ["Reports", "#reports"], "-");
  const play = find("Play");
  play.splice(at(play, "Rest of Season"), 0, ["Play Until...", () => PlayUntil.open(), null, "Ctrl+U"]);
  const file = find("File");
  file.splice(at(file, "Save Game As...") + 1, 0, ["Backups...", () => Backups.open()]);
  Object.assign(SCREEN_NAMES, {leagueday: "Schedule by Day", transactions: "Transactions", depth: "Depth Chart", txnlog: "Transaction Log", milestones: "Milestones",
    reports: "Reports", draftlog: "Past Drafts", season: "Season Page", rules: "Rules", teaminfo: "Team Info", notes: "Notes"});
  Object.assign(TAB_OF, {offseason: "transactions", rights: "transactions", warroom: "transactions", draft: "transactions", freeagents: "transactions", txnlog: "transactions",
    depth: "roster", leagueday: "calendar", milestones: "stats", reports: "stats", draftlog: "stats", season: "stats", rules: "standings", teaminfo: "roster", notes: "dashboard"});
  const nav = document.querySelector('#nav a[data-view="offseason"]');
  if (nav) { nav.dataset.view = "transactions"; nav.setAttribute("href", "#transactions"); }
  document.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "u" && STATE && STATE.started) { e.preventDefault(); PlayUntil.open(); } });
})();

/* ---- boot: moved to the last script (v32.js) ---- */
