/* v46: League > College Hockey: programs, the recruiting board, your prospects in college and the college free-agent
   market (docs/COLLEGE.md). */

const CH = {tab: "programs"};
VIEWS.college = async (arg) => {
  const d = await api("college", arg ? {program: arg} : {});
  if (!d.active) return panel("College hockey", empty("This world has no college league."));
  if (arg && d.program) {
    const p = d.program, i = p.info;
    return panel(`${esc(i.name)}`, `<p>${esc(i.conference)} · prestige <b>${Math.round(i.prestige)}</b> · head coach ${esc(i.coach)} ·
        ${i.titles} title${i.titles === 1 ? "" : "s"}, ${i.frozen_fours} Frozen Four${i.frozen_fours === 1 ? "" : "s"} in this save</p>` +
      table(p.roster, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "pos", label: "Pos"},
        {key: "overall", label: "Overall", num: true, fmt: (r) => r.overall.toFixed(2)}, {key: "class_name", label: "Class"},
        {key: "left", label: "Seasons left", num: true, fmt: (r) => r.left == null ? "" : r.left}, {key: "rights", label: "NHL rights"}]) +
      (p.commits.length ? `<h4>Commitments</h4>` + table(p.commits, [{key: "year", label: "Enrols", fmt: (r) => ssn(r.year)},
        {key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "pos", label: "Pos"}]) : "") +
      `<p><a href="#college">Back to College Hockey</a></p>`);
  }
  const tabs = [["programs", "Programs"], ["recruiting", "Recruiting"], ["mine", "Our prospects"], ["fa", `Free agents${d.fa.filter((x) => x.status === "open").length ? " (" + d.fa.filter((x) => x.status === "open").length + ")" : ""}`]];
  let body = "";
  if (CH.tab === "programs") {
    body = table(d.programs, [{key: "name", label: "Program", fmt: (r) => `<a href="#college/${r.team_id}">${esc(r.short)}</a>`},
      {key: "conference", label: "Conference"}, {key: "prestige", label: "Prestige", num: true, fmt: (r) => `<b>${Math.round(r.prestige)}</b>`},
      {key: "coach", label: "Coach"}, {key: "players", label: "Players", num: true}, {key: "nhl_picks", label: "NHL picks", num: true},
      {key: "commits", label: "Commits", num: true}, {key: "titles", label: "Titles", num: true}]) +
      (d.hobey.length ? `<h4>Hobey Baker Award</h4>` + table(d.hobey, [{key: "season", label: "Season", fmt: (r) => ssn(r.season)},
        {key: "name", label: "Winner", fmt: (r) => clink(r.player_id, r.name)}, {key: "detail", label: ""}]) : "");
  } else if (CH.tab === "recruiting") {
    body = `<p class="muted small">Recruiting rounds are on 15 October and 1 March, with a last round in the summer; commits enrol the next season if they are ready, otherwise the season after.</p>
      <div class="ch-split"><div><h4>Best uncommitted recruits for ${ssn(d.next)}</h4>` +
      table(d.board, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "pos", label: "Pos"}, {key: "nat", label: "Nat"},
        {key: "club", label: "Plays for"}, {key: "quality", label: "Quality", num: true, fmt: (r) => r.quality.toFixed(2)}, {key: "rights", label: "NHL rights"}]) +
      `</div><div><h4>Latest commitments</h4>` +
      table(d.commits, [{key: "day", label: "Date", fmt: (r) => dshort(r.day)}, {key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)},
        {key: "pos", label: "Pos"}, {key: "program", label: "Program", fmt: (r) => `<a href="#college/${r.program_id}">${esc(r.program)}</a>`},
        {key: "year", label: "Enrols", fmt: (r) => ssn(r.year)}, {key: "rights", label: "NHL rights"}]) + `</div></div>`;
  } else if (CH.tab === "mine") {
    body = `<p class="muted small">Steer a prospect: <b>college</b> sends him to school (a good fit for a player who needs time), <b>junior</b> keeps him in junior
      (and withdraws a commitment). While he is in college we hold his rights until the summer after his last college season; a senior can refuse to sign and walk.
      Eligibility: four seasons for players who enrolled before ${ssn(d.rules.new_from)}; from then five seasons in five years, the clock starting at enrolment or the season after he turns 19.</p>` +
      (d.mine.length ? table(d.mine, [{key: "name", label: "Prospect", fmt: (r) => clink(r.player_id, r.name)}, {key: "pos", label: "Pos"},
        {key: "pick", label: "Pick", fmt: (r) => `${r.draft_year} #${r.pick || "-"}`}, {key: "expires", label: "Rights to", num: true},
        {key: "where", label: "Now", fmt: (r) => r.college ? `${esc(r.college.program)}: ${esc(r.college.class_name)}, ${r.college.left} more season${r.college.left === 1 ? "" : "s"}`
          : r.commit ? `${esc(r.where)} · committed to ${esc(r.commit.program)} for ${ssn(r.commit.year)}` : esc(r.where)},
        {key: "path", label: "Path", fmt: (r) => r.college ? "in college" : `<select class="ch-path" data-pid="${r.player_id}">${["none", "college", "junior"].map((p) =>
          `<option value="${p}"${(r.path || "none") === p ? " selected" : ""}>${p === "none" ? "his choice" : p}</option>`).join("")}</select>`}])
        : empty("We hold no unsigned draft picks."));
  } else {
    body = `<p class="muted small">When the NCAA season ends, undrafted players leaving school can sign an entry-level deal with any club. Each decides ten days after the market opens:
      playing time at his position matters most${d.can_now ? "; a deal that starts now (he can play for us this season, using up a year of it) is a plus" : ""}.</p>` +
      (d.fa.length ? table(d.fa, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "pos", label: "Pos"},
        {key: "overall", label: "Overall", num: true, fmt: (r) => r.overall == null ? "-" : r.overall.toFixed(2)}, {key: "reason", label: ""},
        {key: "offers", label: "Offers", num: true}, {key: "status", label: "Status", fmt: (r) => r.signed ? `signed: ${esc(r.signed)}` : esc(r.status) + (r.status === "open" ? ` (decides ${dshort(r.decide_by)})` : "")},
        {key: "act", label: "", fmt: (r) => r.status !== "open" ? "" : r.mine ? `<span class="tag pos">offered${r.mine_now ? ", now" : ""}</span> <a class="btn small ch-wd" data-pid="${r.player_id}">Withdraw</a>`
          : `<a class="btn small ch-of" data-pid="${r.player_id}">Offer</a>${d.can_now ? ` <a class="btn small ch-of" data-pid="${r.player_id}" data-now="1">Offer, start now</a>` : ""}`}])
        : empty("The college free-agent market opens when the NCAA season ends."));
  }
  AFTER = () => {
    document.querySelectorAll("[data-chtab]").forEach((b) => b.onclick = () => { CH.tab = b.dataset.chtab; render(); });
    document.querySelectorAll(".ch-path").forEach((s) => s.onchange = async () => { await cmd(`college path ${s.dataset.pid} ${s.value}`); render(); });
    document.querySelectorAll(".ch-of").forEach((b) => b.onclick = async () => { await cmd(`college offer ${b.dataset.pid}${b.dataset.now ? " now" : ""}`); render(); });
    document.querySelectorAll(".ch-wd").forEach((b) => b.onclick = async () => { await cmd(`college withdraw ${b.dataset.pid}`); render(); });
    decorate($("#view"));
  };
  return panel(`College hockey ${ssn(d.season)}`, `<div class="toolbar"><div class="tabs">${tabs.map(([k, l]) => `<a class="btn${CH.tab === k ? " active" : ""}" data-chtab="${k}">${l}</a>`).join(" ")}</div></div>${body}`);
};
(() => {
  const lg = MENUS.find((m) => m[0] === "League")[1];
  const at = lg.findIndex((x) => Array.isArray(x) && x[0] === "World Leagues");
  lg.splice(at >= 0 ? at + 1 : lg.length, 0, ["College Hockey", "#college"]);
  SCREEN_NAMES.college = "College Hockey";
})();

