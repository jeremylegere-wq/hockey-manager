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
