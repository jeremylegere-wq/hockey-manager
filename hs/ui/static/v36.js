"use strict";
// v36, phase E: scouting and development. The Scouting screen in four tabs (your board with knowledge levels and the
// watch list; your network: scouts' regions, tournament trips, coverage; central scouting's lists; a mock draft with
// suggestions for your pick), training focus on the Development screen, and the development chart on the player.

const LV = (l) => l ? `<span class="lv lv-${l}" title="How well your scouts know him (A best, E barely)">${l}</span>` : "";
const SC_TABS = [["board", "Your board"], ["network", "Scouting network"], ["bureau", "Central scouting"], ["mock", "Mock draft"]];
VIEWS.scouting = async (tab = "board") => {
  const bar = tabBar(SC_TABS.map(([k, l]) => [k, l, `#scouting/${k}`]), tab);
  if (tab === "network") return bar + await scNetwork();
  if (tab === "bureau") return bar + await scBureau();
  if (tab === "mock") return bar + await scMock();
  const d = await api("scouting");
  const t = table(d.board, [{key: "rank", label: "#", num: true}, {key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)},
    {key: "level", label: "Known", fmt: (r) => LV(r.level)}, {key: "pos", label: "Pos"}, {key: "age", label: "Age", num: true},
    {key: "height", label: "Ht", num: true, fmt: (r) => r.height ? (SETTINGS.units === "imperial" ? cm2ftin(r.height) : r.height) : "-"},
    {key: "nat", label: "Nat"}, {key: "club", label: "Playing for"}, {key: "grade", label: "Your scouts say"}, {key: "line", label: "Last season", fmt: (r) => esc(r.line || "")},
    {key: "flags", label: "", fmt: (r) => r.flags.map((f) => `<span class="tag${/exceptional/.test(f) ? " pos" : ""}">${esc(f)}</span>`).join(" ")},
    {key: "w", label: "", fmt: (r) => r.watched ? `<button class="mini" data-cmd="scout unwatch ${r.player_id}">Watching</button>` : `<button class="mini" data-cmd="scout watch ${r.player_id}">Watch</button>`}]);
  return bar + `<div class="grid">${panel(`Your board: the ${d.year} draft`, `<p>Your director of amateur scouting is <b>${esc(d.style_label)}</b>.
    Projections are your scouts' view, not the truth. Your own error is about &plusmn;${d.error}, smaller on prospects your scouts know well
    (A, B) and larger on those they barely know (D, E): put scouts on a region, send them to tournaments, watch players.</p>`)}
    ${panel("Prospects", `<div class="scroll tall">${t}</div>`)}</div>`;
};

async function scNetwork() {
  const d = await api("scoutnet");
  const regionOpts = (cur) => `<option value="all"${cur === "all" ? " selected" : ""}>All regions</option>` + Object.entries(d.regions).map(([k, l]) => `<option value="${k}"${k === cur ? " selected" : ""}>${esc(l)}</option>`).join("");
  const scouts = d.scouts.length ? `<table class="kvt">${d.scouts.map((s) => `<tr><th>${esc(s.name)} <span class="muted small">evaluation ${s.evaluation}</span></th>
      <td><select data-assign="${s.staff_id}">${regionOpts(s.region)}</select></td></tr>`).join("")}
      ${d.director ? `<tr><th>${esc(d.director.name)} <span class="muted small">director, evaluation ${d.director.evaluation}</span></th><td class="muted">watches everywhere, a third of a scout's pace</td></tr>` : ""}</table>`
    : empty("You have no amateur scouts: hire them on the Staff screen.");
  const lv = ["A", "B", "C", "D", "E"];
  const cov = `<table><thead><tr><th>Region</th>${lv.map((l) => `<th class="num">${LV(l)}</th>`).join("")}</tr></thead><tbody>${Object.entries(d.coverage).map(([r, c]) =>
    `<tr><td>${esc(d.regions[r])}</td>${lv.map((l) => `<td class="num">${c[l] || ""}</td>`).join("")}</tr>`).join("")}</tbody></table>
    <p class="muted small">${d.pool.toLocaleString()} prospects eligible for the ${d.year} draft, by how well your scouts know them. Knowledge fades unless it is kept up.</p>`;
  const staff = d.scouts.concat(d.director ? [d.director] : []);
  const ev = table(d.events, [{key: "name", label: "Event"}, {key: "start", label: "When", fmt: (r) => `${dshort(r.start)} - ${dshort(r.end)}`},
    {key: "going", label: "Send", fmt: (r) => staff.map((s) => r.going.includes(s.staff_id) ? `<span class="tag pos">${esc(s.name.split(" ").pop())} going</span>`
      : `<button class="mini" data-cmd="scout trip ${s.staff_id} ${r.key}">${esc(s.name.split(" ").pop())}</button>`).join(" ")}]);
  const wl = d.watchlist.length ? table(d.watchlist, [{key: "name", label: "Player", fmt: (r) => clink(r.pid, r.name)}, {key: "level", label: "Known", fmt: (r) => LV(r.level)},
    {key: "added", label: "Since"}, {key: "x", label: "", fmt: (r) => `<button class="mini" data-cmd="scout unwatch ${r.pid}">Remove</button>`}]) : empty("Watch players from your board: your scouts learn them twice as fast.");
  AFTER = () => document.querySelectorAll("[data-assign]").forEach((s) => (s.onchange = () => cmd(`scout assign ${s.dataset.assign} ${s.value}`)));
  return `<div class="grid three">${panel("Your scouts", scouts)}${panel("Coverage", cov)}${panel("Watch list", wl)}</div>${panel("Tournaments and showcases", ev,
    "a scout who goes comes back knowing everyone he saw much better")}`;
}

const BUR = {stage: null, list: "North American skaters"};
async function scBureau() {
  const d = await api("bureau", BUR.stage ? {stage: BUR.stage} : {});
  if (!d.stage) return panel("Central scouting", empty("The league's central scouting publishes its preliminary list on 15 October, the midterm on 15 January and the final list on 15 April."));
  BUR.stage = d.stage;
  const lists = Object.keys(d.lists);
  if (!lists.includes(BUR.list)) BUR.list = lists[0];
  const st = `<div class="toolbar">${d.stages.map((s) => `<button class="${s === d.stage ? "primary" : ""}" data-stage="${s}">${s[0].toUpperCase() + s.slice(1)}</button>`).join(" ")}<span class="spacer"></span>
    ${lists.map((l) => `<button class="${l === BUR.list ? "primary" : ""}" data-list="${esc(l)}">${esc(l)}</button>`).join(" ")}</div>`;
  AFTER = () => {
    document.querySelectorAll("[data-stage]").forEach((b) => (b.onclick = () => { BUR.stage = b.dataset.stage; render(); }));
    document.querySelectorAll("[data-list]").forEach((b) => (b.onclick = () => { BUR.list = b.dataset.list; render(); }));
  };
  const t = table(d.lists[BUR.list] || [], [{key: "rank", label: "#", num: true}, {key: "name", label: "Player", fmt: (r) => clink(r.pid, r.name)},
    {key: "grade", label: "Grade", fmt: (r) => r.grade ? `<span class="tag">${r.grade}</span>` : ""}, {key: "level", label: "Your scouts know him", fmt: (r) => LV(r.level)}]);
  return st + panel(`Central scouting, ${d.stage} list: ${BUR.list} (${d.year} draft)`, `<div class="scroll tall">${t}</div>
    <p class="muted small">A: a first-round talent, B: second or third round, C: fourth to sixth. Each list is closer to the truth than the one before.</p>`);
}

async function scMock() {
  const d = await api("mock");
  const t = table(d.mock, [{key: "pick", label: "#", num: true}, {key: "abbr", label: "Club", fmt: (r) => tm(r.abbr, r.team_id)},
    {key: "name", label: "Likely pick", fmt: (r) => clink(r.pid, r.name)}, {key: "pos", label: "Pos"}, {key: "level", label: "Known", fmt: (r) => LV(r.level)}],
    {rowClass: (r) => STATE && r.team_id === STATE.team_id ? "mine" : ""});
  const s = d.suggestions;
  const sug = s.items.length ? `<p>As it stands you pick <b>#${s.slot}</b> in the first round.</p><ul class="plain">${s.items.map((x) => `<li><b>${esc(x.kind)}</b>: ${clink(x.pid, x.name)} ${LV(x.level)}
      <span class="muted small">${esc(x.why)}</span></li>`).join("")}</ul>` : empty("No suggestions yet.");
  return `<div class="grid two">${panel("Mock draft: the first round", `<div class="scroll tall">${t}</div><p class="muted small">Order from the standings today (the lottery comes later); each club takes the player its own scouts like best.</p>`)}
    ${panel("Your scouts suggest", sug)}</div>`;
}

/* ================================================================ development: training focus */
const devV36 = VIEWS.development;
VIEWS.development = async () => {
  const d = await api("development");
  const ch = (v) => v == null ? '<span class="muted">-</span>' : `<b class="${v > 0.5 ? "r4" : v < -0.5 ? "r1" : ""}">${v > 0 ? "+" : ""}${v}</b>`;
  const t = table(d.players, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "pos", label: "Pos"}, {key: "age", label: "Age", num: true},
    {key: "status", label: "Where", fmt: (r) => r.status === "prospect" ? '<span class="tag">minors</span>' : "NHL"},
    {key: "was", label: "Value last summer", num: true, fmt: (r) => r.was ?? "-"}, {key: "value", label: "Value today", num: true}, {key: "change", label: "Change", num: true, fmt: (r) => ch(r.change)},
    {key: "focus", label: "Training focus", fmt: (r) => `<select data-train="${r.player_id}">${r.focus_options.map((o) => `<option${o === r.focus ? " selected" : ""}>${o}</option>`).join("")}</select>`}]);
  AFTER = () => document.querySelectorAll("[data-train]").forEach((s) => (s.onchange = () => cmd(`train ${s.dataset.train} ${s.value}`)));
  return panel("Development: your organisation", `<div class="scroll tall">${t}</div><p class="muted small">Each summer a player's overall moves with his age, potential, your coaches and his coachability.
    A training focus decides where the change goes (1.6x in the focus attributes, the rest give it back), not how much; in decline, focus attributes lose less.
    Ceilings move a little each summer, and a few wild cards a lot.</p>`);
};

/* ================================================================ the development chart (player screen, Ratings tab) */
function devChartSvg(d) {
  if (!d.points.length) return empty("No ratings history yet.");
  const W = 520, H = 190, P = 30, cols = ["#3f66a3", "#b3243a", "#2f8a4f", "#a6670f"];
  const vals = d.points.flatMap((p) => d.groups.map((g) => p[g]));
  const lo = Math.floor(Math.min(...vals) - 0.5), hi = Math.ceil(Math.max(...vals) + 0.5);
  const x = (i) => P + (d.points.length === 1 ? (W - 2 * P) / 2 : i * (W - 2 * P) / (d.points.length - 1));
  const y = (v) => H - P + 8 - (v - lo) / (hi - lo || 1) * (H - P - 10);
  const lines = d.groups.map((g, k) => `<polyline fill="none" stroke="${cols[k % 4]}" stroke-width="2" points="${d.points.map((p, i) => `${x(i)},${y(p[g])}`).join(" ")}"/>`
    + d.points.map((p, i) => `<circle cx="${x(i)}" cy="${y(p[g])}" r="3" fill="${cols[k % 4]}"><title>${esc(g)} ${p[g]} (${esc(p.label)})</title></circle>`).join("")).join("");
  const axis = d.points.map((p, i) => `<text x="${x(i)}" y="${H - 4}" text-anchor="middle" font-size="10" fill="#5a6a7f">${esc(p.label)}</text>`).join("")
    + [lo, (lo + hi) / 2, hi].map((v) => `<text x="4" y="${y(v) + 3}" font-size="10" fill="#5a6a7f">${v.toFixed(1)}</text><line x1="${P}" x2="${W - 6}" y1="${y(v)}" y2="${y(v)}" stroke="#e3eaf3"/>`).join("");
  const key = d.groups.map((g, k) => `<span class="dc-key"><i style="background:${cols[k % 4]}"></i>${esc(g)}</span>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" class="devchart">${axis}${lines}</svg><div>${key}${d.wild ? ' <span class="tag warn" title="His ceiling can move a lot from summer to summer">wild card</span>' : ""}</div>`;
}
const playerV36 = VIEWS.player;
VIEWS.player = async (id) => {
  const html = await playerV36(id);
  const prev = AFTER;
  AFTER = async () => {
    if (prev) await prev();
    if ((location.hash.split("/")[2] || "") !== "ratings") return;
    const d = await api("devchart", {id}).catch(() => null);
    if (!d) return;
    const mine = STATE && (await api("people", {id}).catch(() => ({}))).mine;
    const focus = mine ? `<p>Training focus <select id="dc-focus">${d.focus_options.map((o) => `<option${o === d.focus ? " selected" : ""}>${o}</option>`).join("")}</select></p>` : "";
    $("#view").insertAdjacentHTML("beforeend", panel("Development", devChartSvg(d) + focus));
    const f = $("#dc-focus"); if (f) f.onchange = () => cmd(`train ${id} ${f.value}`);
    decorate($("#view"));
  };
  return html;
};

(() => {
  const team = MENUS.find((m) => m[0] === "Team")[1];
  const i = team.findIndex((it) => it !== "-" && it[0] === "Scouting");
  team.splice(i + 1, 0, ["Scouting Network", "#scouting/network"], ["Central Scouting", "#scouting/bureau"], ["Mock Draft", "#scouting/mock"]);
})();

/* ---- boot: moved to the last script (v37.js) ---- */
