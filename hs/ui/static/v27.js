"use strict";
// v27: player profile, team pages (hockeydb style), the stats hub and league history, the trade proposal tray,
// captaincy, the press room, the draft room, playoffs and awards, the free-agency war room, and game setup.
// Loaded after app.js and features.js.

const tlink = (id, label, season) => id ? `<a href="#team/${id}${season ? "/" + season : ""}">${esc(label)}</a>` : esc(label || "");
const n0 = (v) => v == null ? "-" : v;
const f3 = (v) => v == null ? "-" : v.toFixed(3).replace(/^0/, "");
const f2 = (v) => v == null ? "-" : v.toFixed(2);

/* ================================================================ player profile */
VIEWS.player = async (id) => {
  const [p, x] = await Promise.all([api("player", {id}), api("playerx", {id})]);
  const G = p.position === "G";
  const yr = STATE && STATE.season;
  const cur = x.career.filter((r) => r.season === yr && r.split === "RS" && r.league === "NHL");
  const sum = (k) => cur.reduce((a, r) => a + (r[k] || 0), 0);
  const tiles = G ? [["GP", sum("gp")], ["W", sum("w")], ["SV%", cur.length ? f3(cur[cur.length - 1].sv_pct) : "-"], ["GAA", cur.length ? f2(cur[cur.length - 1].gaa) : "-"], ["SO", sum("so")]]
    : [["GP", sum("gp")], ["G", sum("g")], ["A", sum("a")], ["P", sum("p")], ["SOG", sum("sog")]];
  const status = [p.leader ? `<span class="pp-tag lead">${p.leader === "C" ? "Captain" : "Alternate captain"}</span>` : "",
    p.status === "injured" || p.status === "ltir" ? `<span class="pp-tag neg">${p.status === "ltir" ? "LTIR" : "Injured"}${p.injury ? ": " + esc(p.injury.description || "") + (p.injury.expected_return ? ", back about " + esc(p.injury.expected_return) : "") : ""}</span>` : "",
    p.status === "prospect" ? `<span class="pp-tag">In the minors${p.club_name ? ": " + esc(p.club_name) : ""}</span>` : "",
    p.morale && p.morale.trade_request ? '<span class="pp-tag neg">Trade requested</span>' : "",
    ...x.awards.slice(0, 6).map((a) => `<span class="pp-tag award" title="${esc(a.detail || "")}">${esc(a.award)} ${ssn(a.season)}</span>`)].join("");
  const hero = `<div class="pp-hero"><div class="pp-face">${portrait(p.player_id, p.team, p.position, 92)}</div>
    <div class="pp-id"><div class="pp-name">${esc(p.name)}</div>
      <div class="pp-sub">${p.team_id ? tlink(p.team_id, p.team_name || p.team) : p.rights ? `Rights: ${esc(p.rights.team)}` : "Free agent"} · ${esc(p.position)} · shoots ${esc(p.shoots || "-")}
        · age ${p.age} (born ${esc(p.birth_date || "-")}) · ${esc(p.nationality || "")} · ${p.height_cm ? (SETTINGS.units === "imperial" ? `${cm2ftin(p.height_cm)} (${p.height_cm} cm)` : `${p.height_cm} cm (${cm2ftin(p.height_cm)})`) : "-"} · ${p.weight_kg ? (SETTINGS.units === "imperial" ? Math.round(p.weight_kg * 2.2046) + " lb" : p.weight_kg + " kg") : "-"}</div>
      <div class="pp-tags">${status}</div></div>
    <div class="pp-tiles">${tiles.map(([l, v]) => `<div><b>${v}</b><span>${l}</span></div>`).join("")}<div class="val"><b>${p.value}</b><span>value${x.percentile.value != null ? ` · top ${100 - x.percentile.value}%` : ""}</span></div></div></div>`;
  const tab = (location.hash.split("/")[2] || "overview");
  const tabs = [["overview", "Overview"], ["stats", "Career stats"], ["log", "Game log"], ["ratings", "Ratings"], ["contract", "Contract"], ...(p.mine ? [["person", "Personality & morale"]] : []), ["history", "History"]];
  const nav = `<div class="tabs pp-tabs">${tabs.map(([k, l]) => `<a class="btn${k === tab ? " active" : ""}" href="#player/${p.player_id}/${k}">${l}</a>`).join(" ")}</div>`;
  // career table, hockeydb style: season, team (link), league, GP G A P PIM | playoffs
  const seasons = [...new Set(x.career.map((r) => r.season))];
  const careerRows = seasons.map((s) => {
    const rs = x.career.filter((r) => r.season === s && r.split === "RS");
    const po = x.career.filter((r) => r.season === s && r.split === "PO");
    return rs.map((r, i) => {
      const pr = po.find((q) => (r.team_id ? q.team_id === r.team_id : q.team === r.team));   // v42: imported clubs have no id
      const cells = G ? [r.gp, n0(r.w), n0(r.l), n0(r.otl), f3(r.sv_pct), f2(r.gaa), n0(r.so)] : [r.gp, r.g, r.a, r.p, n0(r.pim)];
      const pcells = G ? (pr ? [pr.gp, n0(pr.w), n0(pr.l), f3(pr.sv_pct), f2(pr.gaa)] : ["", "", "", "", ""]) : (pr ? [pr.gp, pr.g, pr.a, pr.p] : ["", "", "", ""]);
      return `<tr class="${r.league === "NHL" ? "nhl" : ""}${r.live ? " live" : ""}"><td>${i === 0 ? ssn(s) : ""}</td><td>${tlink(r.team_id, r.team, r.season)}</td><td>${esc(r.league)}</td>
        ${cells.map((c) => `<td class="num">${c}</td>`).join("")}<td class="sep"></td>${pcells.map((c) => `<td class="num po">${c}</td>`).join("")}</tr>`;
    }).join("");
  }).join("");
  const head = G ? '<th class="num">GP</th><th class="num">W</th><th class="num">L</th><th class="num">OTL</th><th class="num">SV%</th><th class="num">GAA</th><th class="num">SO</th>'
    : '<th class="num">GP</th><th class="num">G</th><th class="num">A</th><th class="num">P</th><th class="num">PIM</th>';
  const phead = G ? '<th class="num">GP</th><th class="num">W</th><th class="num">L</th><th class="num">SV%</th><th class="num">GAA</th>' : '<th class="num">GP</th><th class="num">G</th><th class="num">A</th><th class="num">P</th>';
  const totRows = x.totals.filter((t) => t.split === "RS").map((t) => {
    const po = x.totals.find((q) => q.league === t.league && q.split === "PO");
    const cells = G ? [t.gp, t.w, t.l, t.otl, f3(t.sv_pct), "", t.so] : [t.gp, t.g, t.a, t.p, t.pim];
    const pc = G ? (po ? [po.gp, po.w, po.l, f3(po.sv_pct), ""] : ["", "", "", "", ""]) : (po ? [po.gp, po.g, po.a, po.p] : ["", "", "", ""]);
    return `<tr class="tot"><td colspan="2">${esc(t.league)} totals</td><td>${t.seasons} seasons</td>${cells.map((c) => `<td class="num">${n0(c)}</td>`).join("")}<td class="sep"></td>${pc.map((c) => `<td class="num po">${c}</td>`).join("")}</tr>`;
  }).join("");
  const career = `<div class="scroll hdb"><table class="hdb-table"><thead><tr><th colspan="3"></th><th colspan="${G ? 7 : 5}" class="grp">Regular season</th><th class="sep"></th><th colspan="${G ? 5 : 4}" class="grp">Playoffs</th></tr>
    <tr><th>Season</th><th>Team</th><th>Lge</th>${head}<th class="sep"></th>${phead}</tr></thead><tbody>${careerRows}${totRows}</tbody></table></div>`;
  const log = x.log.length ? table(x.log, [{key: "date", label: "Date"}, {key: "opp", label: "Opp", fmt: (r) => `${r.home ? "vs" : "@"} ${esc(r.opp)}${r.playoff ? ' <span class="tag">PO</span>' : ""}`},
    {key: "result", label: "Result", fmt: (r) => `<a href="#game/${r.game_id}">${esc(r.result)}</a>`},
    ...(G ? [{key: "sa", label: "SA", num: 1}, {key: "sv", label: "SV", num: 1}, {key: "svp", label: "SV%", num: 1, fmt: (r) => r.sa ? f3(r.sv / r.sa) : "-"}]
      : [{key: "g", label: "G", num: 1}, {key: "a", label: "A", num: 1}, {key: "p", label: "P", num: 1, fmt: (r) => r.g + r.a}, {key: "sog", label: "SOG", num: 1}]),
    {key: "toi", label: "TOI", num: 1}]) : '<p class="muted">No NHL games recorded yet.</p>';
  const attrs = `<div class="grid g2">${p.attributes.map((g) => panel(g.title, `<div class="attr">${g.items.map((i) => `<span>${esc(i.label)}</span><span class="v ${ratingClass(i.value)}">${i.value}</span>`).join("")}</div>`)).join("")}</div>`;
  const val = p.valuation ? panel(`Contract value: ${p.valuation.grade} (${p.valuation.words})`, `<p>Worth ${mil(p.valuation.value)} over the rest of the deal, costs ${mil(p.valuation.cost)}: surplus
     <b class="${p.valuation.surplus >= 0 ? "r4" : "r1"}">${p.valuation.surplus >= 0 ? "+" : ""}${mil(p.valuation.surplus)}</b>; ${Math.round(p.valuation.p_positive * 100)}% chance it ends up positive.</p>` +
    table(p.valuation.rows, [{key: "season", label: "Season", fmt: (r) => ssn(r.season)}, {key: "age", label: "Age", num: 1}, {key: "proj", label: "Projected", num: 1}, {key: "war", label: "WAR", num: 1}, {key: "worth", label: "Worth", num: 1, fmt: (r) => mil(r.worth)}])) : "";
  const contract = (p.contract ? panel("Current contract", `<div class="pp-contract"><div><b>${mil(p.contract.cap_hit)}</b><span>cap hit</span></div><div><b>${p.contract.years}</b><span>years</span></div>
      <div><b>${ssn(p.contract.start)}</b><span>first season</span></div><div><b>${ssn(p.contract.ends)}</b><span>final season</span></div><div><b>${esc(ctype(p.contract.type))}</b><span>type</span></div>
      ${p.contract.no_trade ? '<div><b>Yes</b><span>no-trade clause</span></div>' : ""}${p.contract.expiring ? `<div><b>${esc(p.contract.status_at_expiry || "")}</b><span>at expiry</span></div>` : ""}</div>
      ${p.mine && p.contract.expiring ? `<p><button class="primary" data-talks="${p.player_id}">Negotiate an extension</button></p>` : ""}`) : "") + val +
    panel("Contract history", table(p.contracts, [{key: "start_year", label: "From", fmt: (r) => ssn(r.start_year)}, {key: "years", label: "Yrs", num: 1},
      {key: "cap_hit", label: "AAV", num: 1, fmt: (r) => mil(r.cap_hit)}, {key: "team", label: "Team"}, {key: "contract_type", label: "Type", fmt: (r) => esc(ctype(r.contract_type))}]));
  const ev = panel("History", `<ul class="list">${p.events.map((e) => `<li><span class="date">${esc(e.date)}</span>${esc(e.text)}</li>`).join("") || "<li class='muted'>Nothing yet.</li>"}</ul>`);
  let person = "";
  if (p.mine) {
    const m = p.morale;
    person = (m ? panel("Morale", `<dl class="kv">${["morale", "role", "team", "contract", "trust_mgmt", "trust_coach"].map((k) => `<dt>${k.replace("_mgmt", " in you").replace("_coach", " in coach").replace("_", " ")}</dt><dd>${bar(m[k])}</dd>`).join("")}</dl>`) : "")
      + (p.personality ? panel("Personality", `<div class="attr">${Object.entries(p.personality).map(([k, v]) => `<span>${esc(k.replace("_", " "))}</span><span class="v">${v}</span>`).join("")}</div>`) : "");
    if (p.concern) {
      const opts = [["supportive", "Reassure him"], ["direct", "Be candid"], ["firm", "Restate the standard"], ["diplomatic", "Non-committal"]];
      person = panel("Wants to talk", `<p>He ${esc(p.concern.detail)} <span class="date">since ${esc(p.concern.since)}</span></p>
        <div class="row">${opts.map(([a, l]) => `<button data-cmd="respond ${p.player_id} ${a}">${l}</button>`).join("")}</div>
        <p><button class="primary" data-cmd="respond ${p.player_id} promise" data-confirm="This is a binding promise: ${esc(p.concern.promise)}. Breaking it will cost trust. Make it?">Promise: ${esc(p.concern.promise)}</button></p>`) + person;
    }
  }
  const actions = [];
  if (p.mine) {
    if (p.status === "prospect") actions.push(`<button data-cmd="recall ${p.player_id}">Recall</button>`);
    if (p.status === "active") actions.push(`<button data-cmd="senddown ${p.player_id}">Send down</button>`, `<button data-captain="${p.player_id}">Leadership group...</button>`);
    if (p.contract && p.contract.expiring) actions.push(`<button class="primary" data-talks="${p.player_id}">Negotiate extension</button>`);
    actions.push(`<button data-cmd="shop ${p.player_id}" data-confirm="Tell the league ${esc(p.name)} is available? Clubs that need him call over the next days; most open low unless they badly need him. He will hear about it." title="Shop him: interested clubs call over the next two weeks">Shop him...</button>`);
    actions.push(`<button class="danger" data-cmd="release ${p.player_id}" data-confirm="Release him? Any remaining contract is bought out.">Release / buy out</button>`);
  } else if (!p.team && p.status === "active" && !p.rights) {
    actions.push(`<button class="primary" data-talks="${p.player_id}">Negotiate</button>`, `<button data-cmd="sign ${p.player_id}">Sign at his asking price</button>`);
    if (STATE && ["arbitration", "awards", "preseason"].includes(STATE.phase))      // v39 (#18): a professional tryout
      actions.push(`<button data-cmd="pto ${p.player_id}" title="Training camp on a tryout: no contract; the head coach reports on opening day">Invite to camp (tryout)</button>`);
  } else if (p.rights && STATE && p.rights.team === STATE.abbr) {
    actions.push(`<button class="primary" data-cmd="elc ${p.player_id}">Sign entry-level contract</button>`);
  } else if (p.team_id) {
    actions.push(`<a class="btn" href="#trade/${p.team_id}" onclick="TRADE_WANT=${p.player_id}">Trade for him</a>`);
  }
  const side = `${actions.length ? panel("Actions", `<div class="row">${actions.join("")}</div>`) : ""}
    ${panel("Profile", `<dl class="kv"><dt>Club</dt><dd>${esc(p.club || "-")}</dd>${p.projection ? `<dt>Scouts' projection</dt><dd>${esc(p.projection)}</dd>` : ""}
      ${p.rights ? `<dt>Draft rights</dt><dd>${esc(p.rights.team)}, pick ${p.rights.pick} (${p.rights.draft_year}), until ${p.rights.expires}</dd>` : ""}
      ${x.percentile.value != null ? `<dt>League rank</dt><dd>better than ${x.percentile.value}% of ${G ? "goalies" : p.position === "D" ? "defencemen" : "forwards"} in the league</dd>` : ""}</dl>`)}`;
  let body;
  if (tab === "stats") body = panel("Career", career);
  else if (tab === "log") body = panel("Last games", log);
  else if (tab === "ratings") {
    body = attrs + (x.attr_history.length > 1 ? panel("Development", '<div id="pp-dev" class="chart"></div>') : "");
    if (x.attr_history.length > 1) AFTER = async () => {
      await ensurePlotly();
      const h = x.attr_history;
      plot("pp-dev", x.attr_keys.slice(0, 6).map((k) => ({x: h.map((r) => ssn(r.season)), y: h.map((r) => r[k]), name: k.replace(/_/g, " "), mode: "lines+markers"})),
        {yaxis: {title: "rating (1-20)"}, legend: {orientation: "h", y: -0.25}});
    };
  } else if (tab === "contract") body = contract;
  else if (tab === "person") body = person || panel("Personality", "<p class='muted'>Nothing on file.</p>");
  else if (tab === "history") body = ev;
  else body = `<div class="grid g2">${panel("Career summary", career)}<div class="grid">${panel("Last games", log)}${p.contract ? panel("Contract", `<p><b>${mil(p.contract.cap_hit)}</b> a year through ${ssn(p.contract.ends)} (${esc(ctype(p.contract.type))}${p.contract.no_trade ? ", no-trade" : ""})</p>`) : ""}</div></div>` + attrs;
  return hero + nav + `<div class="grid g21"><div class="grid">${body}</div><div class="grid">${side}${tab === "overview" ? ev : ""}</div></div>`;
};

/* ================================================================ team pages */
VIEWS.team = async () => {
  const [, id, season] = location.hash.slice(1).split("/");
  if (!id) return panel("Team", "No team.");
  const d = await api("team", season ? {id, season} : {id});
  const t = d.team;
  const r = d.record;
  const sel = `<select id="tm-season">${d.seasons.map((y) => `<option value="${y}"${y === d.season ? " selected" : ""}>${ssn(y)}</option>`).join("")}</select>`;
  AFTER = () => { const s = $("#tm-season"); if (s) s.onchange = () => { location.hash = `team/${t.team_id}/${s.value}`; }; };
  const hero = `<div class="tm-hero"><div class="tm-crest">${crest(t.abbr, 72)}</div><div><div class="pp-name">${esc(t.name)} ${esc(t.nickname)}</div>
      <div class="pp-sub">${esc(d.league.name || "")}${t.conference ? " · " + esc(t.conference) + " · " + esc(t.division) : ""}${d.parent ? ` · affiliate of ${tlink(d.parent.team_id, d.parent.name)}` : ""}
      ${d.affiliates.length ? " · affiliates: " + d.affiliates.map((a) => `${tlink(a.team_id, a.name)} (${esc(a.league)})`).join(", ") : ""}</div></div>
    <div class="tm-season">Season ${sel}${d.mine ? ' <span class="tag pos">your club</span>' : ""}</div>
    ${r ? `<div class="pp-tiles">${[["GP", r.gp], ["W", r.w], ["L", r.l], ["OTL", r.otl], ["PTS", r.pts], ["GF", r.gf], ["GA", r.ga]].map(([l, v]) => `<div><b>${v}</b><span>${l}</span></div>`).join("")}</div>` : ""}</div>
    ${r && r.playoff_text ? `<p class="tm-result">${ssn(d.season)}: ${r.league_rank ? `${ordinal(r.div_rank)} in the ${esc(t.division)}, ${ordinal(r.league_rank)} overall; ` : ""}${esc(r.playoff_text)}</p>` : ""}`;
  const skCols = [{key: "name", label: "Player", fmt: (x) => plink(x.player_id, x.name)}, {key: "pos", label: "Pos"}, {key: "age", label: "Age", num: 1},
    {key: "gp", label: "GP", num: 1}, {key: "g", label: "G", num: 1}, {key: "a", label: "A", num: 1}, {key: "p", label: "P", num: 1}, {key: "pim", label: "PIM", num: 1},
    {key: "sog", label: "SOG", num: 1}, {key: "sh_pct", label: "SH%", num: 1, fmt: (x) => n0(x.sh_pct)}, {key: "toi_gp", label: "TOI/GP", num: 1, fmt: (x) => n0(x.toi_gp)}];
  const glCols = [{key: "name", label: "Goalie", fmt: (x) => plink(x.player_id, x.name)}, {key: "age", label: "Age", num: 1}, {key: "gp", label: "GP", num: 1},
    {key: "w", label: "W", num: 1}, {key: "l", label: "L", num: 1}, {key: "otl", label: "OTL", num: 1}, {key: "sa", label: "SA", num: 1}, {key: "ga", label: "GA", num: 1},
    {key: "sv_pct", label: "SV%", num: 1, fmt: (x) => f3(x.sv_pct)}, {key: "gaa", label: "GAA", num: 1, fmt: (x) => f2(x.gaa)}, {key: "so", label: "SO", num: 1}];
  const hist = d.history.length ? table(d.history, [{key: "season_start_year", label: "Season", fmt: (h) => tlink(t.team_id, ssn(h.season_start_year), h.season_start_year)},
    {key: "gp", label: "GP", num: 1}, {key: "w", label: "W", num: 1}, {key: "l", label: "L", num: 1}, {key: "otl", label: "OTL", num: 1}, {key: "pts", label: "PTS", num: 1},
    {key: "gf", label: "GF", num: 1}, {key: "ga", label: "GA", num: 1}, {key: "div_rank", label: "Div", num: 1, fmt: (h) => ordinal(h.div_rank)}, {key: "league_rank", label: "League", num: 1, fmt: (h) => ordinal(h.league_rank)},
    {key: "playoff_text", label: "Playoffs", fmt: (h) => `<span class="${h.playoff_round === 5 ? "r4" : ""}">${esc(h.playoff_text)}</span>`}]) : '<p class="muted">No completed seasons in the game yet.</p>';
  const leaders = table(d.leaders, [{key: "name", label: "Player", fmt: (x) => plink(x.player_id, x.name)}, {key: "gp", label: "GP", num: 1}, {key: "g", label: "G", num: 1}, {key: "a", label: "A", num: 1}, {key: "p", label: "P", num: 1}]);
  return `<div class="tabs"><a class="btn" href="#stats">Stats hub</a> <a class="btn" href="#stats/history">League history</a></div>` + hero +
    `<div class="grid g21"><div class="grid">${panel(`Skaters ${ssn(d.season)}`, `<div class="scroll">${table(d.skaters, skCols)}</div>`)}
      ${panel(`Goalies ${ssn(d.season)}`, table(d.goalies, glCols))}
      ${d.playoff_skaters.length ? panel(`Playoffs ${ssn(d.season)}`, table(d.playoff_skaters, skCols.slice(0, 8))) : ""}</div>
      <div class="grid">${panel("Franchise history", `<div class="scroll">${hist}</div>`)}${panel("Franchise leaders (points, all seasons on file)", leaders)}
        ${d.awards.length ? panel("Awards", `<ul class="list">${d.awards.map((a) => `<li><span class="date">${ssn(a.season)}</span><b>${esc(a.award)}</b> ${a.player_id ? clink(a.player_id, "winner") : ""} <span class="muted">${esc(a.detail || "")}</span></li>`).join("")}</ul>`) : ""}
        ${d.staff.length ? panel("Staff", `<ul class="list">${d.staff.map((s) => `<li><span class="tag">${esc(s.role)}</span> ${esc(s.name)}</li>`).join("")}</ul>`) : ""}</div></div>`;
};
function ordinal(n) { if (!n) return "-"; const s = ["th", "st", "nd", "rd"], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }

/* ================================================================ stats hub */
const Hub = {league: "", season: "", split: "RS", pos: "all", team: "", q: "", limit: 100};
VIEWS.stats = async (tab = "leaders") => {
  if (tab === "history") return LeagueHistory.view();
  const d = await api("stats", {season: Hub.season, league: Hub.league, split: Hub.split});
  Hub.season = String(d.season); Hub.league = String(d.league_id);
  const T = [["leaders", "Leaders"], ["skaters", "Skaters"], ["goalies", "Goalies"], ["teams", "Teams"], ["history", "League history"]];
  // v38 (#23): the advanced numbers sit next to the basic ones, not only in the menu
  const ADV = [["#analytics/teams", "Advanced: league"], ["#analytics/team", "Advanced: by club"], ["#analytics/players", "Advanced: players and goalies"], ["#analytics/odds", "Playoff odds"]];
  const ctl = `<div class="tabs">${T.map(([k, l]) => `<a class="btn${k === tab ? " active" : ""}" href="#stats/${k}">${l}</a>`).join(" ")}<span class="tsep"></span>${ADV.map(([h, l]) => `<a class="btn adv" href="${h}">${l}</a>`).join(" ")}<span class="spacer"></span>
    <label>League <select id="hb-league">${d.leagues.map((l) => `<option value="${l.league_id}"${l.league_id === d.league_id ? " selected" : ""}>${esc(l.abbr)}</option>`).join("")}</select></label>
    <label>Season <select id="hb-season">${d.seasons.map((y) => `<option value="${y}"${y === d.season ? " selected" : ""}>${ssn(y)}</option>`).join("")}</select></label>
    <label><select id="hb-split"><option value="RS"${d.split === "RS" ? " selected" : ""}>Regular season</option><option value="PO"${d.split === "PO" ? " selected" : ""}>Playoffs</option></select></label>
    ${d.live ? '<span class="tag pos">live</span>' : ""}</div>`;
  const hook = () => {
    const ch = () => { Hub.league = $("#hb-league").value; Hub.season = $("#hb-season").value; Hub.split = $("#hb-split").value; render(); };
    ["#hb-league", "#hb-season", "#hb-split"].forEach((s) => $(s).onchange = (e) => { if (s === "#hb-league") Hub.season = ""; ch(); });
  };
  let body = "";
  if (tab === "leaders") {
    const fmt = (stat, v) => stat === "sv_pct" ? f3(v) : stat === "gaa" || stat === "ppg" ? f2(v) : n0(v);
    body = `<div class="bc ld"><div class="bc-title">LEAGUE <em>LEADERS</em><span>${esc(d.league || "")} · ${ssn(d.season)}${d.split === "PO" ? " · playoffs" : ""}</span></div><div class="ld-grid">${Object.values(d.leaders).map((c) => {
      const [first, ...rest] = c.rows;
      return `<section class="ld-card"><h3>${esc(c.label)}</h3>${first ? `<div class="ld-first"><div><a href="#player/${first.player_id}">${esc(first.name)}</a><span>${tlink(first.team_id, first.team, d.season)} · ${esc(first.pos)}</span></div><b>${fmt(c.stat, first[c.stat])}</b></div>` : '<p class="muted">-</p>'}
        <ol start="2">${rest.map((r) => `<li class="${r.mine ? "mine" : ""}"><a href="#player/${r.player_id}">${esc(r.name)}</a> <span>${esc(r.team)}</span><b>${fmt(c.stat, r[c.stat])}</b></li>`).join("")}</ol></section>`;
    }).join("")}</div><p class="bc-legend">Rate stats need ${d.min_gp}+ games.</p></div>`;
  } else if (tab === "skaters") {
    let rows = d.skaters.filter((r) => (Hub.pos === "all" || (Hub.pos === "D" ? r.pos === "D" : r.pos !== "D")) && (!Hub.team || r.team.split("/").includes(Hub.team)) && (!Hub.q || r.name.toLowerCase().includes(Hub.q.toLowerCase())));
    rows.sort((a, b) => b.p - a.p || b.g - a.g);
    const teams = [...new Set(d.skaters.flatMap((r) => r.team.split("/")))].sort();
    body = `<div class="row hb-filter"><select id="hb-pos"><option value="all">All skaters</option><option value="F"${Hub.pos === "F" ? " selected" : ""}>Forwards</option><option value="D"${Hub.pos === "D" ? " selected" : ""}>Defence</option></select>
      <select id="hb-team"><option value="">All teams</option>${teams.map((t) => `<option${t === Hub.team ? " selected" : ""}>${esc(t)}</option>`).join("")}</select>
      <input id="hb-q" type="search" placeholder="Find a player" value="${esc(Hub.q)}"> <span class="muted">${rows.length} players</span></div>` +
      panel("Skaters", `<div class="scroll tall">${table(rows.slice(0, Hub.limit), [{key: "rk", label: "#", num: 1, fmt: (r) => rows.indexOf(r) + 1}, {key: "name", label: "Player", fmt: (r) => plink(r.player_id, r.name)},
        {key: "team", label: "Team", fmt: (r) => r.team.includes("/") ? esc(r.team) : tlink(r.team_id, r.team, d.season)}, {key: "pos", label: "Pos"}, {key: "age", label: "Age", num: 1},
        {key: "gp", label: "GP", num: 1}, {key: "g", label: "G", num: 1}, {key: "a", label: "A", num: 1}, {key: "p", label: "P", num: 1}, {key: "ppg", label: "P/GP", num: 1, fmt: (r) => f2(r.ppg)},
        {key: "pim", label: "PIM", num: 1}, {key: "sog", label: "SOG", num: 1}, {key: "sh_pct", label: "SH%", num: 1, fmt: (r) => n0(r.sh_pct)}, {key: "toi_gp", label: "TOI/GP", num: 1, fmt: (r) => n0(r.toi_gp)}],
        {rowClass: (r) => r.mine ? "mine" : ""})}</div>${rows.length > Hub.limit ? `<p><button id="hb-more">Show all ${rows.length}</button></p>` : ""}`);
    const prev = hook;
    AFTER = () => { prev(); $("#hb-pos").onchange = (e) => { Hub.pos = e.target.value; render(); }; $("#hb-team").onchange = (e) => { Hub.team = e.target.value; render(); };
      $("#hb-q").onkeydown = (e) => { if (e.key === "Enter") { Hub.q = e.target.value; render(); } }; const m = $("#hb-more"); if (m) m.onclick = () => { Hub.limit = 5000; render(); }; };
  } else if (tab === "goalies") {
    const rows = d.goalies.slice().sort((a, b) => b.gp - a.gp);
    body = panel("Goalies", `<div class="scroll tall">${table(rows, [{key: "name", label: "Goalie", fmt: (r) => plink(r.player_id, r.name)}, {key: "team", label: "Team", fmt: (r) => r.team.includes("/") ? esc(r.team) : tlink(r.team_id, r.team, d.season)},
      {key: "age", label: "Age", num: 1}, {key: "gp", label: "GP", num: 1}, {key: "gs", label: "GS", num: 1}, {key: "w", label: "W", num: 1}, {key: "l", label: "L", num: 1}, {key: "otl", label: "OTL", num: 1},
      {key: "sa", label: "SA", num: 1}, {key: "ga", label: "GA", num: 1}, {key: "sv_pct", label: "SV%", num: 1, fmt: (r) => f3(r.sv_pct)}, {key: "gaa", label: "GAA", num: 1, fmt: (r) => f2(r.gaa)}, {key: "so", label: "SO", num: 1}],
      {rowClass: (r) => r.mine ? "mine" : ""})}</div>`);
  } else if (tab === "teams") {
    const by = {};
    d.skaters.forEach((r) => { if (r.team.includes("/")) return; const x = by[r.team_id] = by[r.team_id] || {team_id: r.team_id, abbr: r.team, name: r.team_name, g: 0, a: 0, sog: 0, players: 0, top: null};
      x.g += r.g; x.a += r.a; x.sog += r.sog; x.players++; if (!x.top || r.p > x.top.p) x.top = r; });
    d.goalies.forEach((r) => { const x = by[r.team_id]; if (x) { x.ga = (x.ga || 0) + r.ga; x.sa = (x.sa || 0) + r.sa; } });
    const rows = Object.values(by).sort((a, b) => b.g - a.g);
    body = panel("Teams", table(rows, [{key: "abbr", label: "Team", fmt: (r) => tlink(r.team_id, `${r.abbr} ${r.name}`, d.season)}, {key: "players", label: "Skaters used", num: 1},
      {key: "g", label: "Goals", num: 1}, {key: "sog", label: "Shots", num: 1}, {key: "sh", label: "SH%", num: 1, fmt: (r) => r.sog ? (100 * r.g / r.sog).toFixed(1) : "-"},
      {key: "ga", label: "GA", num: 1, fmt: (r) => n0(r.ga)}, {key: "sv", label: "SV%", num: 1, fmt: (r) => r.sa ? f3(1 - r.ga / r.sa) : "-"},
      {key: "top", label: "Top scorer", fmt: (r) => r.top ? `${plink(r.top.player_id, r.top.name)} <span class="muted">${r.top.p} P</span>` : ""}]));
  }
  if (tab !== "skaters") AFTER = hook;
  return ctl + body;
};

const LeagueHistory = {
  async view() {
    const d = await api("leaguehistory");
    const tabs = `<div class="tabs"><a class="btn" href="#stats/leaders">Leaders</a> <a class="btn" href="#stats/skaters">Skaters</a> <a class="btn" href="#stats/goalies">Goalies</a> <a class="btn" href="#stats/teams">Teams</a> <a class="btn active" href="#stats/history">League history</a></div>`;
    const keys = ["hart", "art_ross", "richard", "vezina", "norris", "calder", "conn_smythe", "jack_adams", "presidents"];
    const aw = d.awards.length ? `<div class="scroll"><table><tr><th>Season</th>${keys.map((k) => `<th>${esc(d.award_names[k])}</th>`).join("")}</tr>${d.awards.map((a) => `<tr><td><b>${ssn(a.season)}</b></td>${keys.map((k) => {
      const w = a[k]; return `<td>${w ? (w.player_id ? plink(w.player_id, w.who) : esc(w.who)) + ` <span class="muted">${esc(w.team || "")}</span><div class="muted small">${esc(w.detail || "")}</div>` : "-"}</td>`;
    }).join("")}</tr>`).join("")}</table></div>` : '<p class="muted">Awards are handed out when a simulated season ends.</p>';
    const champs = d.champions.length ? `<div class="champs">${d.champions.map((c) => `<div class="champ"><span>${ssn(c.season)}</span><b>${tlink(c.team_id, c.name, c.season)}</b><i>${c.pts} pts</i></div>`).join("")}</div>` : '<p class="muted">No champions crowned in the game yet.</p>';
    return tabs + `<div class="grid">${panel("Champions", champs)}${panel("Awards", aw)}<div class="grid g2">
      ${panel(`All-time NHL points (seasons on file, since ${ssn(d.since)})`, `<div class="scroll">${table(d.alltime, [{key: "rk", label: "#", num: 1, fmt: (r) => d.alltime.indexOf(r) + 1}, {key: "name", label: "Player", fmt: (r) => plink(r.player_id, r.name) + (r.active ? "" : ' <span class="muted">retired</span>')},
        {key: "pos", label: "Pos"}, {key: "seasons", label: "Seasons", num: 1}, {key: "gp", label: "GP", num: 1}, {key: "g", label: "G", num: 1}, {key: "a", label: "A", num: 1}, {key: "p", label: "P", num: 1}])}</div>`)}
      ${panel("Best single seasons", `<div class="scroll">${table(d.single, [{key: "name", label: "Player", fmt: (r) => plink(r.player_id, r.name)}, {key: "season", label: "Season", fmt: (r) => ssn(r.season)},
        {key: "team", label: "Team", fmt: (r) => tlink(r.team_id, r.team, r.season)}, {key: "gp", label: "GP", num: 1}, {key: "g", label: "G", num: 1}, {key: "a", label: "A", num: 1}, {key: "p", label: "P", num: 1}])}</div>`)}</div></div>`;
  },
};

/* ================================================================ trade proposal tray */
const Tray = {
  card(x, extra = "") {
    return `<div class="tray-card" data-key="${esc(x.key)}">${x.pid ? clink(x.pid, x.name) : `<b>${esc(x.name)}</b>`}<span class="muted">${esc(x.pos)}${x.age ? " · " + x.age : ""}${x.cap ? " · " + mil(x.cap) : ""}</span>
      <i>${x.val}</i>${extra}<button class="tray-x" data-untick="${esc(x.key)}" title="Take out">&times;</button></div>`;
  },
  read(sel) {
    return [...document.querySelectorAll(sel)].map((c) => ({key: c.value, name: c.dataset.name, pos: c.dataset.pos, age: +c.dataset.age || null,
      cap: +c.dataset.cap || 0, val: +c.dataset.val || 0, pid: c.dataset.pid ? +c.dataset.pid : null}));
  },
  two(theirAbbr) {
    const box = $("#tr-tray");
    if (!box) return;
    const give = this.read('.tr-a[data-side="give"]:checked'), get = this.read('.tr-a[data-side="get"]:checked');
    const sum = (xs, k) => xs.reduce((a, x) => a + x[k], 0);
    const room = STATE && STATE.cap ? STATE.cap.room : null;
    const after = room == null ? null : room + sum(give, "cap") - sum(get, "cap");
    box.innerHTML = `<div class="tray-cols"><div><h4>You give</h4>${give.map((x) => this.card(x)).join("") || '<p class="muted">Click players or picks on your side.</p>'}
        <div class="tray-sum">value <b>${sum(give, "val")}</b> · cap out ${mil(sum(give, "cap"))}</div></div>
      <div class="tray-arrow">&#8644;</div>
      <div><h4>You get from ${esc(theirAbbr || "them")}</h4>${get.map((x) => this.card(x)).join("") || '<p class="muted">Click the players or picks you want.</p>'}
        <div class="tray-sum">value <b>${sum(get, "val")}</b> · cap in ${mil(sum(get, "cap"))}</div></div></div>
      ${after != null ? `<p class="tray-cap ${after < 0 ? "neg" : ""}">Your cap room after the trade: <b>${mil(after)}</b>${after < 0 ? " (over the cap: it will be refused)" : ""}</p>` : ""}`;
  },
};
document.addEventListener("click", (e) => {
  const x = e.target.closest("[data-untick]");
  if (x) {
    e.preventDefault();
    const c = document.querySelector(`.tr-a[value="${CSS.escape(x.dataset.untick)}"]:checked`);
    if (c) { c.checked = false; c.dispatchEvent(new Event("change", {bubbles: true})); }
    const s = document.querySelector(`select.t3-to[data-key="${CSS.escape(x.dataset.untick)}"]`);
    if (s) { s.value = ""; s.dispatchEvent(new Event("change", {bubbles: true})); }
    return;
  }
  const row = e.target.closest("tr.tr-row");                   // click anywhere on a row to add or take out
  if (row && !e.target.closest("a, button, input, select")) {
    const c = row.querySelector(".tr-a");
    if (c && !c.disabled) { c.checked = !c.checked; c.dispatchEvent(new Event("change", {bubbles: true})); }
  }
});
document.addEventListener("change", (e) => {
  if (e.target.matches(".tr-a")) Tray.two(document.querySelector("#tr-team option:checked") ? document.querySelector("#tr-team option:checked").textContent.split(" ")[0] : "");
  if (e.target.matches("select.t3-to")) Tray.three();
});
Tray.three = function () {
  const box = $("#t3-tray");
  if (!box) return;
  const legs = [...document.querySelectorAll("select.t3-to")].filter((s) => s.value).map((s) => {
    const tr = s.closest("tr");
    return {key: s.dataset.key, from: s.dataset.from, to: s.value, name: tr.cells[1].innerText.replace(/\s*(core|minors)\s*/g, " ").trim(),
            pid: (tr.querySelector("[data-card]") || {dataset: {}}).dataset.card, pos: tr.cells[2] ? tr.cells[2].innerText : "",
            cap: tr.cells[4] ? tr.cells[4].innerText : "", val: tr.cells[5] ? tr.cells[5].innerText : (tr.cells[2] || {}).innerText};
  });
  const clubs = [...new Set([...document.querySelectorAll("select.t3-to")].map((s) => s.dataset.from))];
  const label = (c) => { const p = document.querySelector(`select.t3-to[data-from="${c}"]`); return p ? p.closest(".panel").querySelector("h2").textContent.replace(" (you)", "") : c; };
  box.innerHTML = `<div class="tray-cols three">${clubs.map((c) => `<div><h4>${esc(label(c))} get</h4>${legs.filter((l) => l.to === c).map((l) => `<div class="tray-card">${l.pid ? clink(+l.pid, l.name) : `<b>${esc(l.name)}</b>`}<span class="muted">from ${esc(label(l.from))}${l.cap && l.cap !== "-" ? " · " + esc(l.cap) : ""}</span><i>${esc(l.val)}</i><button class="tray-x" data-untick="${esc(l.key)}">&times;</button></div>`).join("") || '<p class="muted">Nothing yet.</p>'}</div>`).join("")}</div>`;
};
const trade3Orig = VIEWS.trade3;
VIEWS.trade3 = async (arg) => {
  const html = await trade3Orig(arg);
  return html.replace('<div class="t3-top">', '<div id="t3-tray" class="tray"></div><div class="t3-top">');
};
const tradeV26 = VIEWS.trade;
VIEWS.trade = async (team) => {
  const html = await tradeV26(team);
  const prev = AFTER;
  AFTER = () => { if (prev) prev(); Tray.two(""); };
  return html;
};

/* ================================================================ the leadership group */
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-captain]");
  if (!b) return;
  e.preventDefault();
  Leaders.open(b.dataset.captain ? +b.dataset.captain : null);
});
const Leaders = {
  async open(pre) {
    const d = await api("captaincy");
    const cur = Object.fromEntries(d.current.map((x) => [x.role === "C" ? "C" : "A" + d.current.filter((y) => y.role === "A").indexOf(x), x.player_id]));
    this.sel = {C: pre || cur.C || null, A0: cur.A0 || null, A1: cur.A1 || null};
    if (pre && pre !== cur.C) { const alts = [cur.C, cur.A0, cur.A1].filter((x) => x && x !== pre).slice(0, 2); this.sel.A0 = alts[0] || null; this.sel.A1 = alts[1] || null; }
    this.d = d;
    this.render();
  },
  async render(prev) {
    const d = this.d, sel = this.sel;
    const name = (id) => (d.roster.find((r) => r.player_id === id) || {}).name || "-";
    const opt = (cur) => `<option value="">none</option>` + d.roster.map((r) => `<option value="${r.player_id}"${r.player_id === cur ? " selected" : ""}>${esc(r.name)} (${esc(r.pos)}, ${r.age}) · leadership ${r.leadership} · room ${r.score}${r.role ? " · now " + r.role : ""}</option>`).join("");
    const curC = d.current.find((x) => x.role === "C");
    const pv = prev && prev.preview;
    const conseq = pv ? `<h4>What happens</h4><ul class="ld-fx">${pv.people.map((x) => `<li class="${x.trust < 0 ? "neg" : "pos"}"><b>${esc(x.name)}</b> ${esc(x.change)}: <i>${esc(x.mood)}</i>
        <span class="muted">trust ${x.trust > 0 ? "+" : ""}${x.trust}, morale ${x.morale > 0 ? "+" : ""}${x.morale}${x.trade_request_chance ? `, ${Math.round(x.trade_request_chance * 100)}% he asks for a trade` : ""}</span></li>`).join("")}
        <li>Room cohesion <b class="${pv.cohesion < 0 ? "r1" : "r4"}">${pv.cohesion > 0 ? "+" : ""}${pv.cohesion}</b> · board ${pv.board > 0 ? "+" : ""}${pv.board} · leadership strength ${pv.leadership_strength}/20</li>
        ${pv.notes.map((n) => `<li class="muted">${esc(n[0].toUpperCase() + n.slice(1))}.</li>`).join("")}</ul>` : prev && prev.error ? `<p class="neg">${esc(prev.error)}</p>` : "";
    const replacing = curC && sel.C && curC.player_id !== sel.C ? ` (replacing ${esc(name(curC.player_id))})` : "";
    Modal.open(`<h3>Leadership group</h3><p class="muted">The room has its own idea of who should lead it (the "room" score: leadership, professionalism, experience, standing). Going against it costs cohesion; taking a letter from someone always hurts.</p>
      <div class="ld-now">${["C", "A", "A"].map((r, i) => { const x = d.current.filter((y) => y.role === r)[r === "A" ? i - 1 : 0]; return `<div class="ld-card2"><span class="ltr">${r}</span>${x ? esc(name(x.player_id)) : "<i>vacant</i>"}</div>`; }).join("")}</div>
      <div class="ld-pick"><label>Captain <select id="ld-c">${opt(sel.C)}</select></label><label>Alternate <select id="ld-a0">${opt(sel.A0)}</select></label><label>Alternate <select id="ld-a1">${opt(sel.A1)}</select></label></div>
      <div id="ld-prev">${conseq}</div>
      <p class="row"><button class="primary" id="ld-go"${pv ? "" : " disabled"}>Name ${esc(name(sel.C))} captain${replacing}</button> <button onclick="Modal.close()">Cancel</button></p>
      <p class="muted small">The room's top six: ${d.roster.slice(0, 6).map((r) => esc(r.name)).join(", ")}.</p>`, "saves");
    const upd = async () => {
      this.sel = {C: +$("#ld-c").value || null, A0: +$("#ld-a0").value || null, A1: +$("#ld-a1").value || null};
      if (!this.sel.C) return this.render({error: "Choose a captain."});
      const p = await api("captaincy", {c: this.sel.C, a: [this.sel.A0, this.sel.A1].filter((x) => x).join(",")});
      this.render(p);
    };
    ["#ld-c", "#ld-a0", "#ld-a1"].forEach((x) => $(x).onchange = upd);
    if (!prev) upd();
    $("#ld-go").onclick = async () => {
      const ids = [this.sel.C, this.sel.A0, this.sel.A1].filter((x) => x);
      if (!(await ask(`Name ${name(this.sel.C)} captain${replacing ? replacing.replace(/[()]/g, "") : ""}? This is announced today.`))) return;
      const r = await quietCmd(`leaders ${ids.join(", ")}`);
      if (!r.ok) return toast(r.output, true);
      Modal.open(`<h3>It's done</h3><p>${esc(r.output)}</p><p>The news is out, and the press want to talk about it.</p>
        <p class="row"><a class="btn primary" href="#press" onclick="Modal.close()">Go to the press room</a> <button onclick="Modal.close()">Later</button></p>`, "saves");
      Modal.onclose = () => refresh();
    };
  },
};
const dashV26 = VIEWS.dashboard;
VIEWS.dashboard = async () => {
  const html = await dashV26();
  return html.replace("<h2>Locker room</h2>", '<h2>Locker room<span class="right"><button class="mini" data-captain="">Leadership group</button></span></h2>');
};

/* ================================================================ the press room */
const Press = {
  async open(id) {
    const d = await api("press");
    const ev = d.events.find((e) => e.press_id === id);
    if (!ev) return;
    this.ev = ev; this.i = 0; this.choices = [];
    this.step();
  },
  step() {
    const ev = this.ev, q = ev.questions[this.i];
    const done = ev.questions.slice(0, this.i).map((qq, k) => `<div class="pr-done"><b>${esc(qq.reporter)}</b>: ${esc(qq.text)}<div class="pr-you">You: "${esc(qq.answers[this.choices[k]].text)}"</div></div>`).join("");
    Modal.open(`<div class="pr"><div class="pr-head"><span class="live-dot"></span> ${esc(ev.title)} <span class="muted">question ${this.i + 1} of ${ev.questions.length}</span></div>${done}
      <div class="pr-q"><div class="pr-rep"><span class="pr-av">${esc(q.reporter.split(",")[0].split(" ").map((x) => x[0]).join(""))}</span><div><b>${esc(q.reporter)}</b><div class="muted small">${esc(q.reporter_kind || "")}</div></div></div>
        <p class="pr-text">"${esc(q.text)}"</p></div>
      <div class="pr-answers">${q.answers.map((a, k) => `<button class="pr-a" data-k="${k}"><span class="tag">${esc(a.label)}</span>"${esc(a.text)}"</button>`).join("")}</div></div>`, "press");
    document.querySelectorAll(".pr-a").forEach((b) => b.onclick = () => this.pick(+b.dataset.k));
  },
  async pick(k) {
    this.choices.push(k);
    if (this.i + 1 < this.ev.questions.length) { this.i++; return this.step(); }
    const r = await quietCmd(`answer ${this.ev.press_id} ${this.choices.map((c) => c + 1).join(" ")}`);
    if (!r.ok) return toast(r.output, true);
    const d = await api("press");
    const ev = d.events.find((e) => e.press_id === this.ev.press_id);
    const o = ev.outcome, t = o.totals;
    const meter = (l, v) => { const good = l === "Controversy" ? -v : v; return `<div class="pr-m"><span>${l}</span><b class="${good > 0 ? "r4" : good < 0 ? "r1" : ""}">${v > 0 ? "+" : ""}${v}</b></div>`; };
    Modal.open(`<div class="pr"><div class="pr-head">${esc(ev.title)}: the fallout</div>
      <div class="pr-ms">${meter("Room", t.morale)}${meter("Board", t.board)}${meter("Fans", t.fans)}${meter("Media", t.media)}${meter("Controversy", t.controversy)}</div>
      ${o.lines.length ? `<p>${o.lines.map(esc).join(" ")}</p>` : ""}
      ${o.stories.length ? `<p class="muted">This may not be the end of it: ${[...new Set(o.stories)].map((s) => ({confront: "a player may come to see you", sulk: "a player may go quiet", leak: "the room may talk to reporters", fine: "the league may fine you", coach_rift: "your coach read that", unease: "players are wondering about their futures", praise_pr: "columnists noticed"}[s])).join("; ")}.</p>` : ""}
      <p class="muted">Fan sentiment ${Math.round(o.media.fan_sentiment)}, media ${Math.round(o.media.media_sentiment)}, controversy ${Math.round(o.media.controversy)} (out of 100).</p>
      <p><button class="primary" onclick="Modal.close()">Leave the podium</button></p></div>`, "press");
    Modal.onclose = () => refresh();
  },
};
document.addEventListener("click", (e) => { const b = e.target.closest("[data-press]"); if (b) { e.preventDefault(); Press.open(+b.dataset.press); } });
VIEWS.press = async () => {
  const d = await api("press");
  const m = d.media;
  const meter = (l, v, inv) => `<div class="kpi"><span>${l}</span><b>${Math.round(v)}</b>${bar(inv ? 100 - v : v)}</div>`;
  const pend = d.pending.map((e) => `<div class="pr-card${e.major ? " major" : ""}"><div><b>${esc(e.title)}</b><div class="muted">${esc(e.created)} · ${e.questions.length} questions · until ${esc(e.expires)}${e.major ? " · major" : ""}</div></div>
    <button class="primary" data-press="${e.press_id}">Take the podium</button></div>`).join("") || '<p class="muted">Nobody waiting. Reporters come after games with a story, for availability during the week, at media day, at the deadline, after trades and when you name a captain.</p>';
  const past = d.events.filter((e) => e.status !== "pending").map((e) => `<li><span class="date">${esc(e.created)}</span><b>${esc(e.title)}</b> <span class="tag ${e.status === "expired" ? "warn" : ""}">${e.status === "expired" ? "skipped" : "answered"}</span>
    ${e.answers.map((a) => `<div class="muted small">"${esc(a.text)}"</div>`).join("")}</li>`).join("");
  return `<div class="kpis">${meter("Fan sentiment", m.fan_sentiment)}${meter("Media sentiment", m.media_sentiment)}${meter("Controversy", m.controversy)}</div>
    <div class="grid g2">${panel("Waiting for you", pend)}${panel("On the record", `<ul class="list">${past || "<li class='muted'>Nothing yet.</li>"}</ul>`)}</div>`;
};
const refreshV26 = refresh;
refresh = async function () {
  await refreshV26();
  if (!STATE || !STATE.loaded) return;
  const pp = $("#tb-press"); if (pp) pp.hidden = !!STATE.unemployed;
  if (STATE.unemployed) return;
  try {
    const d = await api("press");
    let pill = $("#tb-press");
    if (!pill) { $("#tb-inbox").insertAdjacentHTML("beforebegin", '<a href="#press" id="tb-press" class="pill link"></a>'); pill = $("#tb-press"); }
    pill.textContent = d.pending.length ? `Press room (${d.pending.length})` : "Press room";
    pill.classList.toggle("alarm", d.pending.some((e) => e.major));
  } catch (e) { /* no game */ }
};

/* ================================================================ the draft room */
const DraftRoom = {
  timer: null, auto: false,
  pace(d) { const p = d.on_clock; return !p ? 0 : p.round === 1 ? 1500 : p.round === 2 ? 700 : 250; },
  stop() { this.auto = false; clearTimeout(this.timer); },
  async step() {
    const r = await quietCmd("draftnext 1");
    if (!r.ok) { this.stop(); toast(r.output, true); }
    return r;
  },
  async run(d) {
    if (!this.auto) return;
    if (!d.on_clock || d.mine_on_clock || d.done) { this.stop(); return render(); }
    this.timer = setTimeout(async () => { await this.step(); if (location.hash.startsWith("#draft")) render(); else this.stop(); }, this.pace(d));
  },
};
VIEWS.draft = async () => {
  const d = await api("draft");
  if (!d.started) {
    DraftRoom.stop();
    return panel("Entry draft", d.phase === "finished" ? `<p>The draft opens on the next offseason phase (late June).</p><button class="primary" data-cmd="offseason">Go to the draft</button>`
      : `<p class="muted">The entry draft is held in late June, after the playoffs.</p>`);
  }
  const oc = d.on_clock;
  const last = [...d.picks].reverse().find((p) => p.player_id);
  const mineNext = d.picks.find((p) => p.mine && !p.player_id);
  const away = mineNext && oc ? mineNext.overall - oc.overall : null;
  const ticker = d.picks.map((p) => `<li class="${p.mine ? "mine" : ""}${oc && p.overall === oc.overall ? " now" : ""}${p.player_id ? "" : " open"}" id="dp-${p.overall}">
      <span class="no">${p.overall}</span><b>${esc(p.abbr)}</b>${p.player_id ? `${clink(p.player_id, p.name)} <span class="muted">${esc(p.pos)}${p.nat ? " · " + esc(p.nat) : ""}</span>` : `<span class="muted">${oc && p.overall === oc.overall ? "on the clock" : ""}</span>`}${p.note ? ` <span class="muted small">${esc(p.note)}</span>` : ""}</li>`).join("");
  const board = d.board ? d.board.map((r) => `<tr><td class="num">${r.rank}</td><td>${clink(r.player_id, r.name)}</td><td>${esc(r.pos)}</td><td class="num">${r.age}</td>
      <td>${esc(r.grade)}</td><td class="num" title="${esc(r.csb_list || "")}">${r.csb ? "#" + r.csb + ' <span class="muted small">' + esc((r.csb_list || "").replace("North American", "NA").replace("International", "Int").replace(" skaters", " sk").replace(" goalies", " G")) + "</span>" : "-"}</td>
      <td class="num">${r.media ? "#" + r.media : "-"}</td><td>${r.range ? `<span class="tag${r.consensus <= 10 ? " pos" : ""}">${esc(r.range)}</span>` : "-"}</td>
      <td class="muted">${esc(r.club || "")}${r.league ? " (" + esc(r.league) + ")" : ""}</td><td class="muted">${esc(r.line || "")}</td>
      <td>${r.flags.map((f) => `<span class="tag">${esc(f)}</span>`).join(" ")}</td><td>${d.mine_on_clock ? `<button class="primary mini" data-cmd="pick ${r.player_id}" data-confirm="Draft ${esc(r.name)} with pick ${oc.overall}?">Draft</button>` : ""}</td></tr>`).join("") : "";
  const stage = d.done ? `<div class="dr-stage"><div class="dr-kick">THE DRAFT IS COMPLETE</div><div class="dr-big">${d.year} entry draft</div>
      <p>Your class: ${d.my_picks.filter((p) => p.player_id).map((p) => `${clink(p.player_id, p.name)} (#${p.overall})`).join(", ") || "no picks"}.</p>
      <p><button class="primary" data-cmd="offseason">On to free agency rights</button></p></div>`
    : `<div class="dr-stage${d.mine_on_clock ? " mine" : ""}"><div class="dr-kick">ROUND ${oc.round} · PICK ${oc.overall}</div>
      <div class="dr-big">${d.mine_on_clock ? "YOU ARE ON THE CLOCK" : esc(oc.team)}</div>
      ${last ? `<div class="dr-last">With pick ${last.overall}, ${esc(last.team)} select <b>${esc(last.name)}</b>, ${esc(last.pos)}${last.nat ? ", " + esc(last.nat) : ""}${last.age ? ", " + last.age : ""}</div>` : ""}
      <div class="row dr-ctl">${d.mine_on_clock ? '<span class="tag pos">Pick from your board</span>' :
        `<button class="primary" id="dr-go">${DraftRoom.auto ? "Pause" : "Run the draft"}</button> <button id="dr-one">Next pick</button> <button id="dr-mine"${mineNext ? "" : " disabled"}>Jump to my pick</button>`}
        <span class="muted">${mineNext ? `Your next pick: #${mineNext.overall} (round ${mineNext.round})${away > 0 ? `, ${away} away` : ""}` : "You have no picks left."}</span></div>
      <div class="dr-clock"><span>Pick clock</span><b id="dr-clock">--:--</b>${d.mine_on_clock ? '<span class="muted small">your scouts pick the top of your board when it runs out</span>' : ""}</div>
      ${DraftDeals.html(d)}</div>`;
  AFTER = () => {
    const el = document.getElementById(`dp-${oc ? oc.overall : 1}`);
    if (el) el.scrollIntoView({block: "center"});
    const go = $("#dr-go");
    if (go) go.onclick = () => { DraftRoom.auto = !DraftRoom.auto; if (DraftRoom.auto) DraftRoom.run(d); else { DraftRoom.stop(); render(); } };
    const one = $("#dr-one"); if (one) one.onclick = async () => { DraftRoom.stop(); await DraftRoom.step(); render(); };
    const mine = $("#dr-mine"); if (mine) mine.onclick = async () => { DraftRoom.stop(); await quietCmd("draftnext 400"); render(); };
    if (DraftRoom.auto) DraftRoom.run(d);
    DraftDeals.clock(d);
  };
  return `<div class="bc dr"><div class="bc-title">ENTRY <em>DRAFT</em><span>${d.year}${d.lottery.length ? " · lottery: " + d.lottery.map((l) => `${esc(l.team)} ${l.from_slot}&rarr;${l.pick}`).join(", ") : ""}</span></div>
    <div class="dr-grid"><ol class="dr-ticker">${ticker}</ol><div>${stage}${d.board ? `<section class="bc-panel dr-board"><h2>Your board <span class="muted small">(your scouts' view)</span></h2>
      <div class="scroll tall"><table class="bc-table small"><tr><th>#</th><th>Prospect</th><th>Pos</th><th>Age</th><th>Your scouts</th><th title="Central scouting: rank within North American / international skaters or goalies">Central scouting</th><th>Media mock</th><th>Consensus</th><th>Playing for</th><th>Last season</th><th>Notes</th><th></th></tr>${board}</table></div></section>` : ""}</div></div></div>`;
};

/* ================================================================ playoffs and awards */
VIEWS.playoffs = async () => {
  const season = location.hash.split("/")[1];
  const d = await api("playoffs", season ? {season} : {});
  if (!d.seasons.length) return panel("Playoffs", "<p class='muted'>The playoffs start when the regular season ends.</p>");
  const ser = (s) => `<div class="po-series" title="${esc(s.label)}">${s.teams.map((t) => `<div class="po-t${t.won ? " won" : ""}${t.mine ? " mine" : ""}"><span>${tlink(t.team_id, t.abbr, d.season)}</span><b>${t.wins}</b></div>`).join("")}
    <details><summary>games</summary>${s.games.map((g) => `<a href="#game/${g.game_id}">G${g.no}: ${esc(g.away)} ${g.ag}-${g.hg} ${esc(g.home)}${g.ot ? " " + g.ot : ""}</a>`).join("<br>")}</details></div>`;
  const col = (rnd, conf, label) => `<div class="po-col"><h4>${label}</h4>${d.rounds[rnd].filter((s) => !conf || s.conf === conf).map(ser).join("")}</div>`;
  const sel = `<select id="po-season">${d.seasons.map((y) => `<option value="${y}"${y === d.season ? " selected" : ""}>${ssn(y)}</option>`).join("")}</select>`;
  AFTER = () => { $("#po-season").onchange = (e) => { location.hash = `playoffs/${e.target.value}`; }; };
  const awards = d.awards.length ? `<div class="aw-grid">${d.awards.map((a) => `<div class="aw"><div class="aw-name">${esc(a.award)}</div><div class="aw-what">${esc(a.what)}</div>
      <div class="aw-who">${a.player_id ? clink(a.player_id, a.who) : esc(a.who || "-")}</div><div class="aw-det">${esc(a.team || "")} · ${esc(a.detail || "")}</div></div>`).join("")}</div>` : "";
  return `<div class="bc"><div class="bc-title">STANLEY CUP <em>PLAYOFFS</em><span>${ssn(d.season)} ${sel}</span></div>
    ${d.champion ? `<div class="po-champ">CHAMPIONS <b>${tlink(d.champion.team_id, d.champion.name, d.season)}</b></div>` : ""}
    <div class="po-bracket">${col(0, "Eastern", "East · Round 1")}${col(1, "Eastern", "East · Round 2")}${col(2, "Eastern", "East final")}
      ${col(3, "", "Final")}${col(2, "Western", "West final")}${col(1, "Western", "West · Round 2")}${col(0, "Western", "West · Round 1")}</div>
    ${awards ? `<div class="bc-title sm">AWARDS <em>NIGHT</em></div>${awards}` : ""}</div>`;
};

/* ================================================================ rights decisions and the free-agency war room */
VIEWS.rights = async () => {
  const d = await api("rights");
  const card = (r) => {
    const rfa = r.status === "RFA";
    const out = r.outcome ? `<span class="tag">${esc(r.outcome)}</span>` : "";
    const q = rfa ? (r.qualified === 1 ? '<span class="tag pos">qualified</span>' : r.qualified === 0 ? '<span class="tag neg">not qualified</span>' : '<span class="tag warn">decide: qualify?</span>') : '<span class="tag warn">UFA: re-sign or he walks on 1 July</span>';
    return `<div class="rt-card${r.decided ? " done" : ""}"><div class="rt-head"><b>${clink(r.player_id, r.name)}</b><span class="muted">${esc(r.pos)} · ${r.age} · value ${r.value}</span><span class="tag">${esc(r.status)}</span></div>
      <div class="rt-body"><span>Last deal ${mil(r.prev_aav)}</span>${rfa && r.qo ? `<span>Qualifying offer ${mil(r.qo)}</span>` : ""}<span>Asks about ${mil(r.asking)}</span><span>Agent: ${esc(r.agent.name)} (${esc(r.agent.style_label)})</span>
        ${r.arb_eligible ? "<span>arbitration eligible</span>" : ""}${r.talks ? `<span>talks: ${esc(r.talks)}</span>` : ""}</div>
      <div class="rt-dec">${out}${r.outcome ? "" : q}</div>
      ${r.outcome ? "" : `<div class="row">${["finished", "rights", "arbitration"].includes(d.phase) ? `<button class="primary" data-talks="${r.player_id}">Negotiate</button>` : ""}
        ${d.phase === "rights" && rfa ? `<button data-cmd="qualify ${r.player_id}">Qualify</button> <button data-cmd="decline ${r.player_id}" data-confirm="Decline to qualify ${esc(r.name)}? He becomes a UFA.">Don't qualify</button>` : ""}
        ${["rights", "arbitration"].includes(d.phase) && rfa && r.arb_eligible && !r.arb_elected_by ? `<button data-cmd="arbitrate ${r.player_id}">Club arbitration</button>` : ""}</div>`}</div>`;
  };
  return `<div class="tabs"><a class="btn" href="#offseason">Offseason</a> <a class="btn active" href="#rights">Your expiring contracts</a> <a class="btn" href="#warroom">Free agency war room</a></div>` +
    panel(`Your expiring contracts${d.undecided ? ` · ${d.undecided} decisions to make` : ""}`, `<p class="muted">Every expiring contract is a decision. Unrestricted free agents walk on 1 July unless you re-sign them; restricted ones need a qualifying offer to keep their rights (or you can sign them now). Talk to the agents before the market opens.</p>
      <div class="rt-grid">${d.rows.map(card).join("") || '<p class="muted">No expiring contracts.</p>'}</div>`);
};
const War = {
  async view() {
    const d = await api("warroom");
    const tabs = `<div class="tabs"><a class="btn" href="#offseason">Offseason</a> <a class="btn" href="#rights">Your expiring contracts</a> <a class="btn active" href="#warroom">Free agency war room</a></div>`;
    if (d.phase === "rights") return tabs + panel("Free agency war room", `<p>The market opens at noon on 1 July. Line up offers now on the Offseason screen (upcoming free agents), or wait for the market.</p>`);
    if (!d.open && !d.last) return tabs + panel("Free agency war room", `<p class="muted">${d.phase === "free_agency" ? "The auction is over: the remaining free agents sign at their asks (Offseason screen)." : "Free agency opens on 1 July."}</p>` +
      (d.log.length ? table(d.log, [{key: "hour", label: "When", fmt: (r) => esc(clock(r.hour))}, {key: "name", label: "Player", fmt: (r) => plink(r.player_id, r.name)}, {key: "team", label: "Club"}, {key: "aav", label: "Deal", num: 1, fmt: (r) => `${r.years} x ${mil(r.aav)}`}, {key: "note", label: "", fmt: (r) => esc(r.note || "")}]) : ""));
    const L = d.last;
    const market = L ? L.market : d.pool;
    const offers = Object.fromEntries(d.offers.map((o) => [o.player_id, o]));
    const rows = market.slice(0, 80).map((m) => {
      const o = offers[m.player_id];
      const heat = m.interest ? "&#9679;".repeat(Math.min(5, m.interest)) : "";
      return `<tr class="${o ? "sel" : ""}"><td>${clink(m.player_id, m.name)}</td><td>${esc(m.pos)}</td><td class="num">${m.age}</td><td class="num">${m.tier ? "T" + m.tier : "-"}</td>
        <td class="num">${m.fair ? mil(m.fair) : "-"}</td><td class="num"><b>${mil(m.ask)}</b>${m.years ? ` <span class="muted">${m.years}y</span>` : ""}</td><td class="heat">${heat}</td>
        <td>${o ? `<b>${o.years} x ${mil(o.aav)}</b> <button class="mini" data-cmd="withdraw ${m.player_id}">Withdraw</button>` : `<span class="row"><input class="wr-aav" data-pid="${m.player_id}" size="6" value="${(m.ask / 1e6).toFixed(2)}">M <select class="wr-yrs" data-pid="${m.player_id}">${[1, 2, 3, 4, 5, 6].map((y) => `<option${y === (m.years || 2) ? " selected" : ""}>${y}</option>`).join("")}</select> <button class="mini primary wr-go" data-pid="${m.player_id}">Offer</button></span>`}</td></tr>`;
    }).join("");
    const feed = d.log.slice().reverse().map((r) => `<li class="${r.user_offer ? "mine" : ""}"><span class="date">${esc(clock(r.hour))}</span><b>${esc(r.team)}</b> sign ${plink(r.player_id, r.name)}: ${r.years} x ${mil(r.aav)}${r.note ? ` <span class="tag">${esc(r.note)}</span>` : ""}</li>`).join("");
    const head = `<div class="wr-clock"><div><div class="dr-kick">1 JULY · FREE AGENCY</div><div class="dr-big">${L ? esc(L.clock) : "Noon: the market opens"}</div>
        <div class="muted">${L ? `Round ${L.round} of ${L.rounds} done${L.next_clock ? ` · next: ${esc(L.next_clock)}` : ""}` : "Make your opening offers, then start the clock."}${L && L.scarcity > 0 ? " · a thin class: prices are high" : ""}</div></div>
      <div class="wr-room">Cap room <b>${d.room != null ? mil(d.room) : "-"}</b></div>
      <div class="row">${d.running ? `<button class="primary" id="wr-next">${L ? "Next round" : "Open the market"}</button> <button id="wr-all">Run to the end</button>` : ""}</div></div>`;
    AFTER = () => {
      const nx = $("#wr-next"); if (nx) nx.onclick = async () => { nx.disabled = true; const r = await quietCmd("faround"); if (!r.ok) toast(r.output, true); else if (r.output) toast(r.output); render(); };
      const al = $("#wr-all"); if (al) al.onclick = async () => { if (!(await ask("Run the rest of the day? Your offers stand; the market moves without you."))) return; const r = await quietCmd("faround all"); toast(r.output, !r.ok); render(); };
      document.querySelectorAll(".wr-go").forEach((b) => b.onclick = async () => {
        const pid = b.dataset.pid, aav = parseFloat(document.querySelector(`.wr-aav[data-pid="${pid}"]`).value), yrs = document.querySelector(`.wr-yrs[data-pid="${pid}"]`).value;
        const r = await quietCmd(`offer ${pid} ${Math.round(aav * 1e6)} ${yrs}`); toast(r.output, !r.ok); render();
      });
    };
    const signedNow = L && L.signed.length ? `<div class="wr-now">${L.signed.slice(0, 8).map((x) => `<div class="wr-sig${x.mine ? " mine" : ""}${x.was_mine && !x.mine ? " lost" : ""}"><b>${esc(x.team)}</b> ${clink(x.player_id, x.name)} <span>${x.years} x ${mil(x.aav)}</span>${x.note ? ` <i>${esc(x.note)}</i>` : ""}${x.was_mine && !x.mine ? " <i>(you lost him)</i>" : ""}</div>`).join("")}</div>` : "";
    return tabs + `<div class="bc wr">${head}${signedNow}</div><div class="grid g21">${panel("The market", `<p class="muted">Asks fall through the day. Dots are clubs that bid on him last round. Offers stand until you withdraw them and are heard every round.</p><div class="scroll tall"><table><tr><th>Player</th><th>Pos</th><th class="num">Age</th><th class="num">Tier</th><th class="num">Fair</th><th class="num">Asks now</th><th>Interest</th><th>Your offer</th></tr>${rows}</table></div>`)}
      ${panel("Signings", `<ul class="list">${feed || "<li class='muted'>Nobody yet.</li>"}</ul>`)}</div>`;
  },
};
function clock(h) { const hh = +h; if (hh >= 24) return `day ${Math.floor(hh / 24) + 1}`; const t = 12 + hh; const hr = Math.floor(t), mi = Math.round((t - hr) * 60); return `${hr > 12 ? hr - 12 : hr}:${String(mi).padStart(2, "0")} pm`; }
VIEWS.warroom = () => War.view();
const offseasonV26 = VIEWS.offseason;
VIEWS.offseason = async () => {
  const html = await offseasonV26();
  const ph = STATE.phase;
  const room = {finished: ["The season is over", "The draft is next. See the playoff bracket and the awards first.", "#playoffs", "Playoffs & awards"],
    draft: ["The entry draft", "Picks are made live in the draft room. Your scouts' board is there.", "#draft", "Enter the draft room"],
    rights: ["Expiring contracts", "Decide on every expiring contract before the market opens on 1 July.", "#rights", "Make the decisions"],
    free_agency: ["Free agency", "The market runs round by round in the war room.", "#warroom", "Enter the war room"],
    arbitration: ["Arbitration", "Hearings are filed. Settle with your players before the hearing.", "#rights", "Your players"],
    awards: ["Arbitration awards", "Awards are in. Walk away from any you cannot afford.", "#offseason", ""],
    preseason: ["Preseason", "Training camp. Set your lines and your leadership group.", "#lines", "Set the lines"]}[ph];
  const banner = room ? `<div class="os-room"><div><div class="dr-kick">${esc(ph.replace("_", " ").toUpperCase())}</div><div class="dr-big">${esc(room[0])}</div><p>${esc(room[1])}</p></div>
    ${room[3] ? `<a class="btn primary big-btn" href="${room[2]}">${esc(room[3])}</a>` : ""}</div>` : "";
  return banner + html;
};
document.addEventListener("click", async (e) => {                    // leaving a phase with decisions left: warn first
  const b = e.target.closest('[data-cmd="offseason"]');
  if (!b) return;
  e.stopImmediatePropagation(); e.preventDefault();                   // decide first (the checks below are async)
  const ph = STATE && STATE.phase;
  let msg = null;
  try {
    if (ph === "draft") { const d = await api("draft"); if (d.my_left) msg = `You still have ${d.my_left} pick${d.my_left === 1 ? "" : "s"}. Your scouts will make ${d.my_left === 1 ? "it" : "them"}. Move on?`; }
    else if (ph === "rights") { const d = await api("rights"); if (d.undecided) msg = `${d.undecided} expiring contract${d.undecided === 1 ? "" : "s"} undecided: RFAs get qualified automatically, UFAs walk. Move on?`; }
    else if (ph === "free_agency") { const d = await api("warroom"); if (d.running) msg = "The free-agency auction is still running. The rest of the day runs without you. Move on?"; }
  } catch (err) { /* fall through */ }
  if (!msg || (typeof SETTINGS !== "undefined" && !SETTINGS.confirm_phase) || (await ask(msg, {ok: "Move on"}))) phaseAdvance(!!msg);
}, true);

/* ================================================================ GM profile and setup */
VIEWS.gm = async () => {
  const d = await api("gm");
  const p = d.profile || {};
  const st = d.stints.map((s) => panel(`${s.team}${s.end ? ` (${esc(s.start || "")} to ${esc(s.end)}, ${esc(s.how_ended || "")})` : s.start ? ` (since ${esc(s.start)})` : ""}`,
    `<div class="pp-contract"><div><b>${s.w}-${s.l}-${s.otl}</b><span>record</span></div><div><b>${s.seasons.length}</b><span>seasons</span></div><div><b>${s.playoffs}</b><span>playoff years</span></div><div><b>${s.cups}</b><span>championships</span></div><div><b>${s.trades}</b><span>trades</span></div></div>` +
    (s.seasons.length ? table(s.seasons, [{key: "season_start_year", label: "Season", fmt: (r) => tlink(s.team_id, ssn(r.season_start_year), r.season_start_year)}, {key: "w", label: "W", num: 1}, {key: "l", label: "L", num: 1},
      {key: "otl", label: "OTL", num: 1}, {key: "pts", label: "PTS", num: 1}, {key: "league_rank", label: "League", num: 1, fmt: (r) => ordinal(r.league_rank)}, {key: "playoff_text", label: "Playoffs"}]) : '<p class="muted">No completed seasons yet.</p>'))).join("");
  return `<div class="pp-hero"><div class="pp-face">${portrait("gm-" + (p.name || "gm"), null, "GM", 92)}</div><div class="pp-id"><div class="pp-name">${esc(p.name || "The GM")}</div>
    <div class="pp-sub">${esc(p.nationality || "")}${p.age ? " · " + p.age : ""}${d.background[0] ? " · background: " + esc(d.background[0]) : ""}</div><div class="pp-tags"><span class="pp-tag">${esc(d.background[1] || "")}</span></div></div></div>` + st;
};
const titleV26 = Title.show.bind(Title);
Title.show = async function (page = "home") {
  if (page !== "new") return titleV26(page);
  const d = await (await fetch("/api/saves")).json();
  const el = $("#title");
  el.hidden = false;
  const S = this.setup = this.setup || {step: 1, name: "", nat: "CAN", bg: "former_player", age: 45, league: null, team: null, save: "", seed: Math.floor(Math.random() * 9000) + 1000};
  const head = `<div class="ts-brand"><i class="live-dot"></i>HOCKEY <em>MANAGER</em></div>`;
  const steps = ["Your GM", "League", "Club", "Start"];
  const bar = `<div class="ts-steps">${steps.map((x, i) => `<span class="${i + 1 === S.step ? "on" : i + 1 < S.step ? "done" : ""}">${i + 1}. ${x}</span>`).join("")}</div>`;
  let body = "";
  if (S.step === 1) {
    body = `<h2>Create your GM</h2><div class="ts-form2"><label>Name <input id="su-name" value="${esc(S.name)}" placeholder="Your name"></label>
      <label>Nationality <select id="su-nat">${["CAN", "USA", "SWE", "FIN", "CZE", "SVK", "RUS", "GER", "SUI", "AUS", "GBR", "OTH"].map((n) => `<option${n === S.nat ? " selected" : ""}>${n}</option>`).join("")}</select></label>
      <label>Age <input id="su-age" size="3" value="${S.age}"></label></div>
      <h4>Background</h4><div class="ts-bgs">${Object.entries(d.backgrounds).map(([k, b]) => `<button class="ts-bg${k === S.bg ? " on" : ""}" data-bg="${k}"><b>${esc(b.label)}</b><span>${esc(b.text)}</span></button>`).join("")}</div>`;
  } else if (S.step === 2) {
    body = `<h2>Choose your league</h2><div class="ts-leagues">${d.leagues.map((l) => `<button class="ts-lg${l.playable ? "" : " off"}${S.league === l.league_id ? " on" : ""}" data-lg="${l.league_id}"${l.playable ? "" : " disabled"}>
      <b>${esc(l.abbr)}</b><span>${esc(l.name)}</span><i>${l.clubs} clubs${l.playable ? "" : " · coming later"}</i></button>`).join("")}</div>
      <p class="muted">For now you can run an NHL club. The other leagues play on around you: your prospects develop there, and their stars come through the draft and free agency.</p>`;
  } else if (S.step === 3) {
    const byDiv = {};
    d.teams.forEach((t) => (byDiv[`${t.conference} · ${t.division}`] = byDiv[`${t.conference} · ${t.division}`] || []).push(t));
    const t = d.teams.find((x) => x.abbr === S.team);
    body = `<h2>Choose your club</h2><div class="ts-club"><div class="ts-divs">${Object.entries(byDiv).map(([k, ts]) => `<div class="ts-div"><h4>${esc(k)}</h4>${ts.map((x) => `<button class="ts-team${x.abbr === S.team ? " on" : ""}" data-team="${esc(x.abbr)}"><b>${esc(x.abbr)}</b> ${esc(x.name)}</button>`).join("")}</div>`).join("")}</div>
      <div class="ts-detail">${t ? `<div class="dr-big">${esc(t.name)}</div><p class="muted">${esc(t.conference)} · ${esc(t.division)}</p><p>Outlook: <b>${esc(t.outlook)}</b> (roster strength ${t.strength})</p>
        <h4>Stars</h4><ul>${t.stars.map((s) => `<li>${esc(s.name)} <span class="muted">${esc(s.pos)}</span></li>`).join("")}</ul><p class="muted">The owner, his expectations and your staff are revealed when you take the job.</p>` : '<p class="muted">Pick a club to see its outlook.</p>'}</div></div>`;
  } else {
    const t = d.teams.find((x) => x.abbr === S.team);
    S.save = S.save || `${S.team} career`;
    body = `<h2>Ready</h2><p><b>${esc(S.name || "The GM")}</b> (${esc(d.backgrounds[S.bg].label)}), general manager of the <b>${esc(t ? t.name : S.team)}</b>.</p>
      <div class="ts-form2"><label>Save name <input id="su-save" value="${esc(S.save)}"></label><label>World seed <input id="su-seed" size="6" value="${S.seed}"></label></div>`;
  }
  el.innerHTML = `<div class="ts-wrap">${head}<div class="ts-panel">${bar}${body}<div class="row ts-nav"><button id="su-back">${S.step === 1 ? "Main menu" : "Back"}</button><span class="spacer"></span>
    <button class="primary big-btn" id="su-next">${S.step === 4 ? "Start career" : "Next"}</button></div></div></div>`;
  const keep = () => {
    if ($("#su-name")) { S.name = $("#su-name").value; S.nat = $("#su-nat").value; S.age = +$("#su-age").value || 45; }
    if ($("#su-save")) { S.save = $("#su-save").value; S.seed = +$("#su-seed").value || 1; }
  };
  el.querySelectorAll("[data-bg]").forEach((b) => b.onclick = () => { keep(); S.bg = b.dataset.bg; this.show("new"); });
  el.querySelectorAll("[data-lg]").forEach((b) => b.onclick = () => { S.league = +b.dataset.lg; this.show("new"); });
  el.querySelectorAll("[data-team]").forEach((b) => b.onclick = () => { S.team = b.dataset.team; this.show("new"); });
  $("#su-back").onclick = () => { keep(); if (S.step === 1) { this.setup = null; Title.show("home"); } else { S.step--; this.show("new"); } };
  $("#su-next").onclick = async () => {
    keep();
    if (S.step === 1 && !S.name.trim()) return toast("Give your GM a name.", true);
    if (S.step === 2 && !S.league) { const nhl = d.leagues.find((l) => l.playable); S.league = nhl ? nhl.league_id : null; }
    if (S.step === 3 && !S.team) return toast("Pick a club.", true);
    if (S.step < 4) { S.step++; return this.show("new"); }
    $("#su-next").disabled = true; $("#su-next").textContent = "Building the league...";
    try {
      await post("/api/save", {action: "new", team: S.team, name: S.save, seed: S.seed, profile: {name: S.name, nationality: S.nat, background: S.bg, age: S.age}});
      this.setup = null; el.hidden = true; location.hash = "#dashboard"; await refresh();
    } catch (err) { toast(err.message, true); $("#su-next").disabled = false; $("#su-next").textContent = "Start career"; }
  };
};

window.addEventListener("hashchange", () => { if (!$("#modal").hidden) Modal.close(); });   // a modal never outlives the page it was opened on

/* ---- boot moved to classic.js (keep it last there) ---- */
// refresh() is called at the end of classic.js
