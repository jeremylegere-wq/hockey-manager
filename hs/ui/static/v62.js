/* v0.62: the staff index and team alumni (issue #16), and a link from the Free Agent Centre to the transfer summary
   (issue #9). */

const SX = {role: "", team: ""};
VIEWS.staffindex = async () => {
  const d = await api("staffindex", Object.assign({}, SX.role ? {role: SX.role} : {}, SX.team !== "" ? {team: SX.team} : {}));
  const head = `<div class="toolbar"><label>Role <select id="sx-role"><option value="">Every role</option>${d.roles.map((r) => `<option value="${r.key}"${r.key === SX.role ? " selected" : ""}>${esc(r.label)}</option>`).join("")}</select></label>
    <label>Club <select id="sx-team"><option value="">The whole league</option><option value="0"${SX.team === "0" ? " selected" : ""}>Available (no club)</option>${d.clubs.map((c) => `<option value="${c.team_id}"${String(c.team_id) === SX.team ? " selected" : ""}>${esc(c.abbr)}</option>`).join("")}</select></label>
    <span class="spacer"></span><span class="muted">${d.rows.length} people</span></div>`;
  AFTER = () => {
    $("#sx-role").onchange = (e) => { SX.role = e.target.value; render(); };
    $("#sx-team").onchange = (e) => { SX.team = e.target.value; render(); };
  };
  const rows = table(d.rows, [
    {key: "name", label: "Name", fmt: (r) => esc(r.name) + (r.is_you ? ' <span class="tag">you</span>' : "")},
    {key: "role_name", label: "Role"}, {key: "team", label: "Club", fmt: (r) => r.team ? tm(r.team, r.team_id) : '<span class="muted">available</span>'},
    {key: "age", label: "Age", num: true}, {key: "main_value", label: "Main skill", num: true, fmt: (r) => `${r.main_value} <span class="muted small">${esc(r.main)}</span>`},
    {key: "reputation", label: "Reputation", num: true}, {key: "style", label: "Style", fmt: (r) => esc(r.style || "")},
    {key: "contract_end", label: "Contract to", fmt: (r) => r.contract_end ? ssn(r.contract_end) : ""},
    {key: "history", label: "Moves in this save", fmt: (r) => r.moves.length ? r.moves.map((m) => `<span class="tag${m.what === "hired" ? " pos" : " neg"}">${esc(m.what)}</span> ${esc(m.team)} <span class="muted small">${esc(m.date)}</span>`).join("<br>") : '<span class="muted small">-</span>'}],
    {rowClass: (r) => STATE && r.team_id === STATE.team_id ? "mine" : ""});
  return head + panel("Staff index", `<div class="scroll tall">${rows}</div><p class="muted small">Every head coach, assistant, goalie coach, development coach, scout, trainer and analyst in the league, with each hiring and firing since the save began.</p>`);
};

const AL = {former: false};
VIEWS.alumni = async (team) => {
  const d = await api("alumni", team ? {team} : {});
  const rows = d.rows.filter((r) => !AL.former || !r.current);
  const sk = rows.filter((r) => !r.goalie), gk = rows.filter((r) => r.goalie);
  const yrs = (r) => r.first === r.last ? ssn(r.first) : `${ssn(r.first)} to ${ssn(r.last)}`;
  const P = {key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, POS = {key: "pos", label: "Pos"};
  const YRS = {key: "first", label: "With the club", fmt: yrs}, NOW = {key: "now", label: "Now", fmt: (r) => r.current ? '<span class="tag pos">with the club</span>' : esc(r.now)};
  const skt = table(sk, [P, POS, YRS, {key: "seasons", label: "Seasons", num: true}, {key: "gp", label: "GP", num: true}, {key: "g", label: "G", num: true},
    {key: "a", label: "A", num: true}, {key: "pts", label: "Pts", num: true}, {key: "pim", label: "PIM", num: true}, {key: "po_gp", label: "Playoff GP", num: true}, {key: "po_pts", label: "Playoff Pts", num: true}, NOW]);
  const gkt = table(gk, [P, YRS, {key: "seasons", label: "Seasons", num: true}, {key: "gp", label: "GP", num: true}, {key: "w", label: "W", num: true},
    {key: "so", label: "SO", num: true}, {key: "sv_pct", label: "SV%", num: true, fmt: (r) => r.sv_pct != null ? r.sv_pct.toFixed(3).replace(/^0/, "") : "-"}, {key: "po_gp", label: "Playoff GP", num: true}, NOW]);
  AFTER = () => { $("#al-former").onchange = (e) => { AL.former = e.target.checked; render(); }; };
  return `<div class="toolbar"><b>${crest(d.team, 18)} ${esc(d.name)}: alumni</b> <a class="btn" href="#team/${d.team_id}">Team page</a>
    <span class="spacer"></span><label class="chk"><input type="checkbox" id="al-former"${AL.former ? " checked" : ""}> former players only (${d.former})</label></div>` +
    panel(`Skaters (${sk.length})`, sk.length ? `<div class="scroll tall">${skt}</div>` : empty("Nobody yet.")) +
    panel(`Goaltenders (${gk.length})`, gk.length ? gkt : empty("Nobody yet.")) +
    '<p class="muted small">Regular season and playoffs, from this save and the history the world was built with. Most games first.</p>';
};

(() => {
  SCREEN_NAMES.staffindex = "Staff Index";
  SCREEN_NAMES.alumni = "Alumni";
  const lg = MENUS.find((m) => m[0] === "League")[1];
  const at = lg.findIndex((x) => Array.isArray(x) && x[0] === "League History");
  lg.splice(at >= 0 ? at + 1 : lg.length, 0, ["Staff Index", "#staffindex"]);
  const t = MENUS.find((m) => m[0] === "Team")[1];
  const oh = t.findIndex((x) => Array.isArray(x) && x[0] === "Organisation History");
  t.splice(oh >= 0 ? oh + 1 : t.length, 0, ["Alumni", () => { location.hash = `#alumni/${STATE.team_id || ""}`; }]);
  // the team page links to its alumni
  const teamV62 = VIEWS.team;
  if (teamV62) {
    VIEWS.team = async (...args) => {
      const html = await teamV62(...args);
      const id = location.hash.slice(1).split("/")[1] || "";
      if (!/^\d+$/.test(id)) return html;
      return html + `<p><a class="btn" href="#alumni/${id}">Alumni: everyone who has played for the club</a></p>`;
    };
  }
  // the Free Agent Centre links to the transfer summary
  const faV62 = VIEWS.freeagents;
  if (faV62) VIEWS.freeagents = async (...args) => (await faV62(...args)).replace('<span class="spacer"></span>', '<span class="spacer"></span><a class="btn" href="#transactions/summary">Transfer summary</a> ');
})();

/* v0.62 (#14): the development centre shows the staff's coaching points by category and the goalie coach's slots */
DEVF["goalie coach"] = "Goalie coach";
const devV62 = VIEWS.development;
VIEWS.development = async () => {
  const html = await devV62();
  let d;
  try { d = await api("development"); } catch (e) { return html; }
  const bar = (v) => `<span class="cp-bar"><i style="width:${Math.round(v / 20 * 100)}%"></i></span>`;
  const pts = d.coaching.map((c) => `<tr><td>${esc(c.category)}</td><td class="num"><b>${c.points.toFixed(1)}</b></td><td>${bar(c.points)}</td><td class="num">x${c.boost.toFixed(2)}</td></tr>`).join("");
  const gs = d.goalie_slots;
  const used = gs.goalies.filter((g) => g.slot).length;
  const grows = gs.goalies.map((g) => `<tr><td>${clink(g.player_id, g.name)}</td><td class="num">${g.age}</td><td>${g.status === "prospect" ? '<span class="tag">minors</span>' : "NHL"}</td>
    <td>${g.slot === "chosen" ? '<span class="tag pos">your choice</span>' : g.slot === "auto" ? '<span class="tag">by default</span>' : '<span class="muted">no slot</span>'}</td>
    <td class="num">${g.factor === 1 ? '<span class="muted">-</span>' : `x${g.factor.toFixed(2)}`}</td>
    <td>${g.slot === "chosen" ? `<button class="mini" data-cmd="goalieslot remove ${g.player_id}">Free the slot</button>` : `<button class="mini" data-cmd="goalieslot add ${g.player_id}">Give him a slot</button>`}</td></tr>`).join("");
  const extra = `<div class="grid two">${panel("Coaching points by category", `<table><tr><th>Category</th><th class="num">Points</th><th></th><th class="num" title="How much more of a gain the focus attributes take">Focus boost</th></tr>${pts}</table>
      <p class="muted small">Your staff's strength in each training focus: offence and defence from your assistant coaches and head coach, skating and physical from the development coach,
      mental from the head coach's communication and leadership, positioning and reflexes from the goaltending coach. 10 is average; a focus takes x1.6 of its share at 10, from x1.4 to x1.8.</p>`)}
    ${panel(`Goalie training slots (${used} of ${gs.n})`, gs.goalies.length ? `<table><tr><th>Goalie</th><th class="num">Age</th><th>Where</th><th>Slot</th><th class="num">Development</th><th></th></tr>${grows}</table>` : empty("No goalies in the organisation."))
      .replace("</section>", `<p class="muted small">Your goaltending coach works one-on-one with ${gs.n} goalies (three with a coaching rating of 14, four with 18). A goalie 24 or under in a slot develops faster with a better coach; one without a slot, 3% slower. Open slots go to your youngest goalies by default.</p></section>`)}</div>`;
  return html + extra;
};

/* v0.62 (#12): the press room shows how your club is covered */
const pressV62 = VIEWS.press;
VIEWS.press = async () => {
  const html = await pressV62();
  let d;
  try { d = await api("press"); } catch (e) { return html; }
  const p = d.profile;
  if (!p) return html;
  const kinds = {star: "the star", phenom: "the phenom", contract: "the contract"};
  const focus = p.focus.map((f) => `<li>${clink(f.player_id, f.name)} <span class="muted">${esc(kinds[f.kind] || f.kind)}</span></li>`).join("") || '<li class="muted">Nobody yet.</li>';
  return html + `<div class="grid two">${panel("How you are covered", `<dl class="kv"><dt>Coverage</dt><dd><b>${p.coverage}</b> of 5 (${esc(p.coverage_words)})</dd>
      <dt>The local media</dt><dd>${esc(p.attitude_words)}</dd><dt>After a quiet game</dt><dd>a press conference about one game in ${Math.round(1 / p.postgame)}</dd>
      <dt>Pressure at the podium</dt><dd>starts at ${p.pressure}</dd></dl>
      <p class="muted small">Coverage follows your market: more reporters, more press conferences and more riding on each answer. The media's mood drifts toward the results and toward its lean.</p>`)}
    ${panel("Who they are watching", `<ul class="list">${focus}</ul><p class="muted small">The players the media follows this season: questions about a player go to them first.</p>`)}</div>`;
};
