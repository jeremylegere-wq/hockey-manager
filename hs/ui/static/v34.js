"use strict";
// v34, phase C: money. The Finances screen: this season's books, the gate and attendance, ticket prices, budgets,
// the arena, the league's attendance, the seasons' history and a full-season projection.

const M = (v) => v == null ? "-" : `${v < 0 ? "-" : ""}$${(Math.abs(v) / 1e6).toFixed(1)}M`;
VIEWS.finances = async (season) => {
  const d = await api("finances", season ? {season} : {});
  const f = d.profile, L = d.ledger;
  const line = (label, k) => `<tr><th>${esc(label)}</th><td class="num ${(L[k] || 0) < 0 ? "r1" : ""}">${M(L[k] || 0)}</td></tr>`;
  const result = d.revenue - d.costs;
  const books = `<table class="kvt fin">${line("Gate", "gate")}${line("Concessions and merchandise", "concessions")}${line("Media", "media")}${line("Sponsorship", "sponsorship")}
      <tr class="tot"><th>Revenue</th><td class="num"><b>${M(d.revenue)}</b></td></tr>
      ${line("Players", "payroll")}${line("Staff", "staff")}${line("Arena", "arena")}${line("Travel", "travel")}${line("Administration", "admin")}
      ${line("Scouting budget", "scouting")}${line("Development budget", "development")}${line("Marketing budget", "marketing")}
      ${L.arena_capital ? line("Arena projects", "arena_capital") : ""}${L.owner ? line("The owner", "owner") : ""}
      <tr class="tot"><th>${result >= 0 ? "Profit" : "Loss"} so far</th><td class="num"><b class="${result >= 0 ? "r4" : "r1"}">${M(result)}</b></td></tr></table>
    <p class="muted small">Cash in the bank: <b>${M(f.cash)}</b>. Media and sponsorship arrive monthly; players are paid over the seven months of the regular season.</p>`;
  const p = d.projection;
  const proj = `<div class="fin-proj"><div><b>${M(p.revenue)}</b><span>revenue</span></div><div><b>${M(p.costs)}</b><span>costs</span></div>
    <div><b class="${p.profit >= 0 ? "r4" : "r1"}">${M(p.profit)}</b><span>result</span></div><div><b>${Math.round(p.fill * 100)}%</b><span>full</span></div></div>
    <p class="muted small">A full season at today's prices, form and fan mood.</p>`;
  const prices = `<table class="kvt">${Object.entries(d.prices).map(([k, x]) => `<tr><th>${{lower: "Lower bowl", upper: "Upper bowl", premium: "Premium and suites"}[k]}
      <span class="muted small">${x.seats.toLocaleString()} seats</span></th><td>$<input class="fin-in" data-price="${k}" value="${Math.round(x.price)}" size="5">
      <span class="muted small">reference $${x.ref}</span></td></tr>`).join("")}</table>
    <p class="muted small">Above the reference, fewer seats sell (the upper bowl is the most sensitive, premium the least); below it, more, up to a sell-out. Playoff tickets sell at 1.6x.</p>`;
  const budgets = `<table class="kvt">${Object.entries(d.budgets).map(([k, x]) => `<tr><th>${k[0].toUpperCase() + k.slice(1)}</th><td>$<input class="fin-in" data-budget="${k}" value="${(x.amount / 1e6).toFixed(2)}" size="5">M a year
      <span class="muted small">default ${M(x.default)}, ${M(x.range[0])}-${M(x.range[1])}</span></td></tr>`).join("")}</table>
    <p class="muted small">Now: scouts' error x${d.effects.scouting}, development x${d.effects.development}, fans' mood ${d.effects.marketing >= 0 ? "+" : ""}${d.effects.marketing} a week. Every AI club spends the defaults.</p>`;
  const arena = `<table class="kvt"><tr><th>Capacity</th><td>${f.capacity.toLocaleString()}</td></tr><tr><th>Quality</th><td>${bar(f.arena_quality)}</td></tr><tr><th>Market</th><td>${f.market} of 10</td></tr></table>
    <p class="row"><button data-ask="improve">Renovate...</button> <button data-ask="expand">Add seats...</button></p>
    <p class="muted small">Offseason only, paid from cash: ${M(d.arena.cost_point)} a point of quality (up to 95), $${d.arena.cost_seat.toLocaleString()} a seat (up to 22,000). Quality lifts demand a little every game.</p>`;
  const games = d.games.length ? table(d.games, [{key: "day", label: "Date", fmt: (r) => dshort(r.day)}, {key: "opp", label: "Visitor", fmt: (r) => tm(r.opp)},
    {key: "total", label: "Crowd", num: true, fmt: (r) => r.total.toLocaleString()}, {key: "fill", label: "Full", num: true, fmt: (r) => `${Math.round(100 * r.total / r.capacity)}%`},
    {key: "gate", label: "Gate", num: true, fmt: (r) => M(r.gate)}]) : empty("No home games yet this season.");
  const league = d.league.length ? table(d.league.map((r, i) => ({...r, rank: i + 1})), [{key: "rank", label: "#", num: true}, {key: "abbr", label: "Club", fmt: (r) => tm(r.abbr, r.team_id)},
    {key: "avg", label: "Average", num: true, fmt: (r) => r.avg.toLocaleString()}, {key: "fill", label: "Full", num: true, fmt: (r) => `${(r.fill * 100).toFixed(1)}%`}],
    {rowClass: (r) => STATE && r.team_id === STATE.team_id ? "mine" : ""}) : empty("No games yet.");
  const hist = d.history.length ? table(d.history, [{key: "season", label: "Season", fmt: (r) => ssn(r.season)}, {key: "revenue", label: "Revenue", num: true, fmt: (r) => M(r.revenue)},
    {key: "costs", label: "Costs", num: true, fmt: (r) => M(r.costs)}, {key: "profit", label: "Result", num: true, fmt: (r) => `<span class="${r.profit >= 0 ? "r4" : "r1"}">${M(r.profit)}</span>`},
    {key: "owner", label: "Owner", num: true, fmt: (r) => M(r.owner)}, {key: "fill", label: "Full", num: true, fmt: (r) => `${(r.fill * 100).toFixed(1)}%`}]) : empty("The first season closes after the playoffs.");
  AFTER = () => {
    document.querySelectorAll("[data-price]").forEach((x) => (x.onchange = () => cmd(`tickets ${x.dataset.price} ${x.value}`)));
    document.querySelectorAll("[data-budget]").forEach((x) => (x.onchange = () => cmd(`budget ${x.dataset.budget} ${x.value}`)));
    document.querySelectorAll("[data-ask]").forEach((b) => (b.onclick = async () => {
      const imp = b.dataset.ask === "improve";
      const v = await ask(imp ? `Arena quality is ${f.arena_quality.toFixed(0)}. How many points of renovation (${M(d.arena.cost_point)} each)?` : `Capacity is ${f.capacity.toLocaleString()}. How many seats to add ($${d.arena.cost_seat.toLocaleString()} each)?`, {input: imp ? "5" : "500", ok: "Build"});
      if (v) cmd(`arena ${b.dataset.ask} ${parseInt(v, 10)}`);
    }));
    const s = $("#fin-s"); if (s) s.onchange = (e) => { location.hash = `#finances/${e.target.value}`; };
  };
  const head = `<div class="toolbar"><label>Season <select id="fin-s">${d.seasons.map((x) => `<option value="${x}"${x === d.season ? " selected" : ""}>${ssn(x)}</option>`).join("")}</select></label>
    <span>Attendance <b>${d.attendance.avg.toLocaleString()}</b> a game, <b>${(d.attendance.fill * 100).toFixed(1)}%</b> full over ${d.attendance.games} home games</span><span class="spacer"></span><span>Cash <b>${M(f.cash)}</b></span></div>`;
  return head + `<div class="grid three">${panel(`The books ${ssn(d.season)}`, books)}<div>${panel("If things go on like this", proj)}${panel("Ticket prices", prices)}</div>
      <div>${panel("Budgets", budgets)}${panel("The arena", arena)}</div></div>
    <div class="grid three">${panel("Recent home games", games)}${panel("League attendance", `<div class="scroll">${league}</div>`)}${panel("Seasons", hist)}</div>`;
};

(() => {
  const team = MENUS.find((m) => m[0] === "Team")[1];
  team.splice(team.findIndex((it) => it !== "-" && it[0] === "Contracts and Cap") + 1, 0, ["Finances", "#finances"]);
  Object.assign(SCREEN_NAMES, {finances: "Finances"});
  Object.assign(TAB_OF, {finances: "contracts"});
})();

/* ---- boot: moved to the last script (v35.js) ---- */
