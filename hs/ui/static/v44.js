/* v44: the World Leagues screen: every league around the NHL, its rules, standings, playoffs, champions and leaders. */

const WL = {league: null, season: null, tab: "table"};
VIEWS.worldleagues = async (arg) => {
  if (arg) WL.league = +arg;
  const d = await api("worldleagues", Object.assign({}, WL.league ? {league: WL.league} : {}, WL.season ? {season: WL.season} : {}));
  WL.league = d.league_id;
  const groups = {};
  d.leagues.forEach((l) => (groups[l.group] = groups[l.group] || []).push(l));
  const order = ["North American pro", "Europe", "Junior", "College", "Other"];
  const picker = order.filter((g) => groups[g]).map((g) => `<div class="wl-grp"><h4>${esc(g)}</h4>${groups[g].map((l) =>
    `<a class="wl-lg${l.league_id === d.league_id ? " on" : ""}" href="#worldleagues/${l.league_id}" title="${esc(l.name)}">
      <b>${esc(l.abbr)}</b><span>${esc(l.name)}</span><i>${l.clubs} clubs${l.mode === "games" ? " · games played" : ""}${l.champion ? ` · ${ssn(l.champion.season)}: ${esc(l.champion.name)}` : ""}</i></a>`).join("")}</div>`).join("");
  const cur = d.leagues.find((l) => l.league_id === d.league_id) || {};
  AFTER = () => {
    document.querySelectorAll("[data-wltab]").forEach((b) => b.onclick = () => { WL.tab = b.dataset.wltab; render(); });
    const s = $("#wl-season"); if (s) s.onchange = () => { WL.season = +s.value; render(); };
    document.querySelectorAll(".wl-lg").forEach((a) => a.addEventListener("click", () => { WL.season = null; }));
  };
  const tabs = (d.mode === "games" ? [["table", "Standings"], ["playoffs", "Playoffs"]] : [["table", "Clubs"]])
    .concat([["leaders", "Scoring leaders"], ["champions", "Champions"], ["rules", "Rules"]]);
  if (!tabs.some(([k]) => k === WL.tab)) WL.tab = "table";
  const seasonSel = `<label>Season <select id="wl-season">${d.seasons.map((y) => `<option value="${y}"${y === d.shown ? " selected" : ""}>${ssn(y)}</option>`).join("")}</select></label>`;
  let body = "";
  if (WL.tab === "table" && d.mode === "games") {
    const confs = [...new Set(d.standings.map((r) => r.conference))];
    const showConf = confs.length > 1 && confs.length < d.standings.length;
    body = table(d.standings, [{key: "rank", label: "#", num: 1}, {key: "name", label: "Club", fmt: (r) => tlink(r.team_id, r.name)},
      ...(showConf ? [{key: "conference", label: "Conf"}] : []), {key: "gp", label: "GP", num: 1}, {key: "w", label: "W", num: 1},
      {key: "l", label: "L", num: 1}, {key: "otl", label: "OTL", num: 1}, ...(d.standings.some((r) => r.t) ? [{key: "t", label: "T", num: 1}] : []),
      {key: "pts", label: "PTS", num: 1}, {key: "gf", label: "GF", num: 1}, {key: "ga", label: "GA", num: 1}]);
    if (d.next_game) body = `<p class="muted small">Next game: ${esc(d.next_game)}</p>` + body;
  } else if (WL.tab === "table") {
    body = `<p class="muted small">This league is simulated a season at a time: no schedule is played, each player gets his season's line and the strongest clubs usually come out on top.</p>` +
      table(d.clubs, [{key: "name", label: "Club", fmt: (r) => tlink(r.team_id, r.name)}, {key: "players", label: "Players", num: 1},
        {key: "strength", label: "Strength", num: 1, fmt: (r) => r.strength == null ? "-" : r.strength.toFixed(2)}]);
  } else if (WL.tab === "playoffs") {
    const rounds = {};
    d.series.forEach((s) => (rounds[s.round] = rounds[s.round] || []).push(s));
    body = Object.keys(rounds).length ? Object.entries(rounds).map(([r, ss]) => `<h4>${esc((ss[0].label || "round " + r).replace(/^./, (c) => c.toUpperCase()))}</h4>
      <table class="dv-t">${ss.map((s) => `<tr><td>${s.seed_a ? `<span class="muted">${s.seed_a}</span> ` : ""}${s.winner === s.a ? `<b>${esc(s.a)}</b>` : esc(s.a)}</td>
        <td class="num">${s.kind === "agg" ? `${s.pts_a}-${s.pts_b} pts` : `${s.wins_a}-${s.wins_b}`}</td>
        <td>${s.seed_b ? `<span class="muted">${s.seed_b}</span> ` : ""}${s.winner === s.b ? `<b>${esc(s.b)}</b>` : esc(s.b)}</td>
        <td class="muted small">${s.kind === "agg" ? "two games on points" : s.best_of === 1 ? "single game" : "best of " + s.best_of}</td></tr>`).join("")}</table>`).join("")
      : '<p class="muted">The playoffs start when the regular season ends.</p>';
  } else if (WL.tab === "leaders") {
    body = d.leaders.length ? `<p class="muted small">${ssn(d.leaders_season)} regular season</p>` + table(d.leaders, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)},
      {key: "team", label: "Club"}, {key: "gp", label: "GP", num: 1}, {key: "g", label: "G", num: 1}, {key: "a", label: "A", num: 1}, {key: "p", label: "P", num: 1}])
      : '<p class="muted">No games on file yet this season.</p>';
  } else if (WL.tab === "champions") {
    body = d.champions.length ? table(d.champions, [{key: "season", label: "Season", fmt: (r) => ssn(r.season)},
      {key: "champion", label: "Champion", fmt: (r) => tlink(r.champion_id, r.champion)}, {key: "runner_up", label: "Runner-up", fmt: (r) => esc(r.runner_up || "-")}])
      : '<p class="muted">No champion crowned in this career yet.</p>';
  } else {
    body = `<ul class="wl-rules">${d.rules.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
      <p class="muted small">${cur.strength != null ? `Strength (the average overall of its better players): ${(+cur.strength).toFixed(2)}. ` : ""}${cur.country ? `Country: ${esc(cur.country)}.` : ""}</p>`;
  }
  return `<div class="wl">${panel("World leagues", `<div class="wl-pick">${picker}</div>`)}
    ${panel(`${esc(cur.name || "")}`, `<div class="toolbar"><div class="tabs">${tabs.map(([k, l]) => `<a class="btn${WL.tab === k ? " active" : ""}" data-wltab="${k}">${l}</a>`).join(" ")}</div><span class="spacer"></span>${seasonSel}</div>${body}`)}</div>`;
};
(() => {
  const lg = MENUS.find((m) => m[0] === "League")[1];
  const at = lg.findIndex((x) => Array.isArray(x) && x[0] === "League History");
  lg.splice(at >= 0 ? at + 1 : lg.length, 0, ["World Leagues", "#worldleagues"]);
  SCREEN_NAMES.worldleagues = "World Leagues";
})();

