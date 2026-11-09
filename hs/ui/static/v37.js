"use strict";
// v37, phase F: the calendar. League > Exhibitions (pre-season and the prospects tournaments, your camp report, the
// calendar options), League > All-Star Weekend, League > Hall of Fame, League > GM Leaders, Manager > Achievements,
// and the rivalries panel on Team Info.

const exScore = (g) => `${esc(g.home)} <b>${esc(g.score)}</b> ${esc(g.away)}${g.ot ? " " + g.ot : ""}`;
const rating1 = (v) => v == null ? "-" : `<b class="${v >= 7.5 ? "r4" : v >= 6.3 ? "r3" : v >= 5.2 ? "r2" : "r1"}">${Number(v).toFixed(1)}</b>`;

const Ex = {year: null, kind: ""};
VIEWS.exhibitions = async (arg) => {
  const d = await api("exhibitions", Object.assign({}, Ex.year ? {year: Ex.year} : {}, Ex.kind ? {kind: Ex.kind} : {}));
  const years = d.years.map((y) => `<option value="${y}"${y === d.year ? " selected" : ""}>${y}</option>`).join("");
  const bar = `<div class="toolbar"><label>Year <select id="ex-year">${years || "<option>-</option>"}</select></label>
    <label>Show <select id="ex-kind">${[["", "Everything"], ["PS", "Pre-season"], ["PROSPECTS", "Prospects tournaments"]].map(([k, l]) => `<option value="${k}"${k === Ex.kind ? " selected" : ""}>${l}</option>`).join("")}</select></label>
    <span class="spacer"></span><a class="btn" href="#allstar">All-Star Weekend</a></div>`;
  const champs = d.champions.length ? `<ul class="plain">${d.champions.map((c) => `<li><b>${esc(c.event)}</b>: ${tm(c.abbr, c.champion)}</li>`).join("")}</ul>` : empty("No prospects tournaments yet: they are played when the pre-season phase opens.");
  const camp = d.camp.length ? table(d.camp, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name) + (r.prospect ? ' <span class="tag">prospect</span>' : "")},
    {key: "pos", label: "Pos"}, {key: "gp", label: "GP", num: true}, {key: "g", label: "G", num: true}, {key: "a", label: "A", num: true},
    {key: "rating", label: "Rating", num: true, fmt: (r) => rating1(r.rating)}]) : empty("Your pre-season games are played when the regular season is scheduled.");
  const byEvent = {};
  d.games.forEach((g) => (byEvent[g.event] = byEvent[g.event] || []).push(g));
  const games = Object.entries(byEvent).map(([ev, gs]) => panel(ev, table(gs, [{key: "day", label: "Date", fmt: (r) => dshort(r.day)},
    {key: "round", label: "Round", fmt: (r) => esc(r.kind === "PS" ? "Game " + r.round : r.round)}, {key: "score", label: "Result", fmt: (r) => `<a href="#exbox/${r.ex_id}">${exScore(r)}</a>`}],
    {rowClass: (r) => r.mine ? "mine" : ""}))).join("") || empty("No exhibitions yet.");
  const o = d.options;
  const opt = (k, vals) => `<select data-opt="${k}">${vals.map((v) => `<option${String(o[k]) === String(v) ? " selected" : ""}>${v}</option>`).join("")}</select>`;
  const opts = `<table class="kvt"><tr><th>Pre-season games a club</th><td>${opt("preseason_games", [0, 2, 4, 6, 8, 10])}</td></tr>
    <tr><th>All-star format</th><td>${opt("allstar", ["conference", "draft", "world", "off"])}</td></tr>
    <tr><th>Prospects tournaments</th><td>${opt("prospects", ["on", "off"])}</td></tr>
    <tr><th>Hall of Fame</th><td>${opt("hof", ["committee", "auto"])}</td></tr></table>
    <p class="muted small">Exhibitions never count in the standings or the season's statistics. Committee: you get a Hall of Fame vote every summer.</p>`;
  AFTER = () => {
    $("#ex-year").onchange = (e) => { Ex.year = e.target.value; render(); };
    $("#ex-kind").onchange = (e) => { Ex.kind = e.target.value; render(); };
    document.querySelectorAll("[data-opt]").forEach((s) => (s.onchange = () => cmd(`events set ${s.dataset.opt} ${s.value}`)));
    decorate($("#view"));
  };
  return bar + `<div class="grid two">${panel("Your camp: pre-season", camp)}<div>${panel("Prospects tournament champions", champs)}${panel("Calendar options", opts)}</div></div>` + games;
};

VIEWS.exbox = async (id) => {
  const d = await api("exbox", {id});
  if (d.missing) return panel("Exhibition", empty("No such game."));
  const side = (i) => table(d.sides[i], [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name) + (r.club && d.kind !== "PS" ? ` <span class="muted small">${esc(r.club)}</span>` : "")},
    {key: "pos", label: "Pos"}, {key: "g", label: "G", num: true}, {key: "a", label: "A", num: true}, {key: "sog", label: "SOG", num: true},
    {key: "saves", label: "SV", num: true, fmt: (r) => r.sa ? `${r.saves}/${r.sa}` : ""}, {key: "rating", label: "Rating", num: true, fmt: (r) => rating1(r.rating)}]);
  const head = `<div class="toolbar"><a class="btn" href="${d.kind === "ASG" ? "#allstar" : "#exhibitions"}">&#9664; Back</a><b>${esc(d.event)}${d.round ? " · " + esc(d.round) : ""} · ${dlong(d.day)}</b></div>
    <h2 class="exh-score">${esc(d.names[0])} ${d.score[0]} - ${d.score[1]} ${esc(d.names[1])}${d.ot ? " (" + d.ot + ")" : ""}</h2>`;
  AFTER = () => decorate($("#view"));
  return head + `<div class="grid two">${panel(d.names[0], side(0))}${panel(d.names[1], side(1))}</div>`;
};

const AS = {year: null};
VIEWS.allstar = async () => {
  const d = await api("allstar", AS.year ? {year: AS.year} : {});
  const years = d.years.length ? `<label>Year <select id="as-year">${d.years.map((y) => `<option${y === d.year ? " selected" : ""}>${y}</option>`).join("")}</select></label>` : "";
  let body = "";
  if (d.game) {
    const g = d.game;
    body += panel("All-Star Game", `<h2 class="exh-score"><a href="#exbox/${g.ex_id}">${esc(g.names[0])} ${g.score[0]} - ${g.score[1]} ${esc(g.names[1])}</a>${g.ot ? " (" + g.ot + ")" : ""}</h2>
      ${d.mvp ? `<p>MVP: ${clink(d.mvp.player_id, d.mvp.name)}</p>` : ""}`);
    const roster = (i) => table(g.sides[i], [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "club", label: "Club"}, {key: "pos", label: "Pos"},
      {key: "g", label: "G", num: true}, {key: "a", label: "A", num: true}, {key: "rating", label: "Rating", num: true, fmt: (r) => rating1(r.rating)}]);
    body += `<div class="grid two">${panel(g.names[0], roster(0))}${panel(g.names[1], roster(1))}</div>`;
  } else {
    body += panel("All-star weekend", d.date ? `<p>${dlong(d.date)} · format: <b>${esc(d.format)}</b> (change it on League &gt; Exhibitions).</p>` : empty("No all-star game this season (an Olympic break, or the option is off)."));
    if (d.projected) {
      const roster = (pl) => table(pl, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "club", label: "Club"}, {key: "pos", label: "Pos"}, {key: "pts", label: "Pts", num: true}]);
      body += `<p class="muted">If the rosters were picked today:</p><div class="grid two">${panel(d.projected.sides[0], roster(d.projected.players[0]))}${panel(d.projected.sides[1], roster(d.projected.players[1]))}</div>`;
    }
  }
  if (d.skills) {
    body += panel("Skills competition", `<div class="grid three">${Object.values(d.skills).map((s) => `<div><h4>${esc(s.name)}</h4><ol>${s.results.map((r) => `<li>${clink(r.player_id, r.name)} <span class="muted">${esc(r.team)}</span> <b>${r.value}</b> ${esc(s.unit)}</li>`).join("")}</ol></div>`).join("")}</div>`);
  }
  AFTER = () => { const y = $("#as-year"); if (y) y.onchange = (e) => { AS.year = e.target.value; render(); }; decorate($("#view")); };
  return `<div class="toolbar">${years}<span class="spacer"></span><a class="btn" href="#exhibitions">Exhibitions</a></div>` + body;
};

VIEWS.hof = async () => {
  const d = await api("hof");
  const mine = d.ballot.filter((b) => b.my_vote).map((b) => b.player_id);
  const ballot = d.ballot.length ? table(d.ballot, [
    {key: "vote", label: d.open && d.mode === "committee" ? "Vote" : "", fmt: (r) => d.open && d.mode === "committee" ? `<input type="checkbox" class="hof-v" value="${r.player_id}"${r.my_vote ? " checked" : ""}>` : (r.inducted ? '<span class="tag pos">inducted</span>' : "")},
    {key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "pos", label: "Pos"}, {key: "last", label: "Last season", num: true},
    {key: "score", label: "Case", num: true, fmt: (r) => `<b>${Math.round(r.score)}</b>`}, {key: "line", label: "Career"},
    {key: "votes", label: "Votes", num: true, fmt: (r) => r.votes == null ? "" : `${r.votes}/${d.committee}`}])
    + (d.open && d.mode === "committee" ? `<div class="toolbar"><span class="muted">Vote for up to ${d.max}; ${d.need} of ${d.committee} votes induct. The vote is when the re-signing phase opens.</span><span class="spacer"></span><button class="primary" id="hof-go">Cast my vote</button></div>` : "")
    : empty(`No ballot yet: it opens when a season ends. A retired player is eligible ${d.wait} seasons after his last.`);
  const members = d.members.length ? table(d.members, [{key: "year", label: "Class", num: true}, {key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)},
    {key: "pos", label: "Pos"}, {key: "votes", label: "Votes", num: true, fmt: (r) => `${r.votes}/${r.of}`}, {key: "line", label: "Career"}]) : empty("Nobody has been inducted in this save yet.");
  AFTER = () => {
    const b = $("#hof-go");
    if (b) b.onclick = () => {
      const ids = [...document.querySelectorAll(".hof-v:checked")].map((x) => x.value);
      if (ids.length > d.max) { toast(`Up to ${d.max} votes.`); return; }
      if (!ids.length) { toast("Tick at least one player."); return; }
      cmd(`hof vote ${ids.join(", ")}`);
    };
    decorate($("#view"));
  };
  return panel(`Ballot ${d.ballot_year || ""}`, ballot) + panel("Hall of Fame", members);
};

VIEWS.gmleaders = async () => {
  const d = await api("gmleaders");
  const rows = d.leaders;
  AFTER = () => decorate($("#view"));
  return panel("GM leaders", rows.length ? table(rows, [{key: "rank", label: "#", num: true},
    {key: "name", label: "General manager", fmt: (r) => `${r.you ? "<b>" + esc(r.name) + " (you)</b>" : esc(r.name)}${r.current ? "" : ' <span class="muted small">former</span>'}`},
    {key: "club_now", label: "Club", fmt: (r) => r.club_now ? esc(r.club_now) : "-"}, {key: "score", label: "GM score", num: true, fmt: (r) => `<b>${r.score}</b>`},
    {key: "seasons", label: "Seasons", num: true}, {key: "rec", label: "Record", fmt: (r) => `${r.w}-${r.l}-${r.otl}`}, {key: "pts_pct", label: "Pts%", num: true, fmt: (r) => r.pts_pct == null ? "-" : f3(r.pts_pct)},
    {key: "playoffs", label: "Playoffs", num: true}, {key: "finals", label: "Finals", num: true}, {key: "cups", label: "Titles", num: true},
    {key: "clubs", label: "Clubs", fmt: (r) => esc(r.clubs.join(", "))}], {rowClass: (r) => r.you ? "mine" : ""})
    + '<p class="muted small">A season scores (points % - .500) x 100, +5 a playoff round reached, +10 more for the title, +8 for GM of the year. Kept from the first season this save finishes.</p>'
    : empty("GM scores start when the first season of this save is over."));
};

VIEWS.achievements = async () => {
  const d = await api("achievements");
  const g = d.gm;
  AFTER = () => decorate($("#view"));
  return `<div class="kpis"><div class="kpi"><span>Achievements</span><b>${d.earned} / ${d.total}</b></div><div class="kpi"><span>GM score</span><b>${g.score}</b></div>
    <div class="kpi"><span>GM rank</span><b>${g.rank ? `${ordinal(g.rank)} of ${g.of}` : "-"}</b></div></div>`
    + panel("Achievements", `<ul class="ach">${d.achievements.map((a) => `<li class="${a.day ? "got" : ""}"><b>${esc(a.name)}</b><span>${esc(a.desc)}</span><i>${a.day ? dshort(a.day) : ""}</i></li>`).join("")}</ul>`);
};

const teaminfoV37 = VIEWS.teaminfo;
VIEWS.teaminfo = async (id) => {
  const html = await teaminfoV37(id);
  const team = id || (STATE && STATE.team_id);
  const r = await api("rivalries", team ? {team} : {}).catch(() => null);
  if (!r) return html;
  const bar = (p) => `<span class="riv-bar"><i style="width:${Math.min(100, p)}%"></i></span>`;
  const rows = r.rivals.map((x) => `<tr><td>${tm(x.abbr, x.team_id)}</td><td>${bar(x.points)} ${Math.round(x.points)}</td><td><b>${esc(x.level)}</b>${x.warming ? ' <span class="tag">warming</span>' : ""}</td>
    <td>${x.h2h.w}-${x.h2h.l}-${x.h2h.otl}</td><td class="num">${x.h2h.series}</td></tr>`).join("");
  const main = r.main ? `<p>Main rival: ${tm(r.main.abbr, r.main.team_id)} (<b>${esc(r.main.level)}</b>)</p>` : '<p class="muted">No main rival yet: a rivalry needs 50 points (playoff meetings make them).</p>';
  return html + panel("Rivalries", main + `<table class="data"><thead><tr><th>Club</th><th>Heat</th><th>Level</th><th>All-time</th><th class="num">Playoff series</th></tr></thead><tbody>${rows}</tbody></table>
    <p class="muted small">Rivalry games (50+) are big games: the big-game players step up, the gate is up, and your fans swing harder on the result.</p>`);
};

Object.assign(SCREEN_NAMES, {exhibitions: "Exhibitions", exbox: "Exhibition", allstar: "All-Star Weekend", hof: "Hall of Fame", gmleaders: "GM Leaders", achievements: "Achievements"});
Object.assign(TAB_OF, {exhibitions: "standings", exbox: "standings", allstar: "standings", hof: "stats", gmleaders: "stats", achievements: "dashboard"});
(() => {
  const league = MENUS.find((m) => m[0] === "League")[1];
  league.push("-", ["Exhibitions", "#exhibitions"], ["All-Star Weekend", "#allstar"], ["Hall of Fame", "#hof"], ["GM Leaders", "#gmleaders"]);
  const mgr = MENUS.find((m) => m[0] === "Manager")[1];
  const i = mgr.findIndex((it) => it !== "-" && it[0] === "Manager Profile");
  mgr.splice(i + 1, 0, ["Achievements", "#achievements"]);
})();

/* ---- boot: moved to the last script (v38.js) ---- */
