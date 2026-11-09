/* v40: player development (docs/DEVELOPMENT.md): the development centre, mentors, training intensity, the monthly
   log on the player's Ratings tab. Loads last; boots the app. */

const DEVF = {ice: "Ice time", level: "Level", character: "Character", mentor: "Mentor", training: "Training", injury: "Injury", staff: "Coaches", coachability: "Coachability"};
const devChips = (f) => Object.entries(f).filter(([k, v]) => Math.abs(v - 1) >= 0.005).map(([k, v]) => devChip(k, v)).join("") || '<span class="muted small">a normal pace</span>';
const devChip = (k, v) => `<span class="dvf ${v > 1.005 ? "up" : v < 0.995 ? "dn" : ""}" title="${esc(DEVF[k] || k)} x${v.toFixed(2)}">${esc((DEVF[k] || k).split(" ")[0])} ${v > 1 ? "+" : ""}${Math.round((v - 1) * 100)}%</span>`;
VIEWS.development = async () => {
  const d = await api("development");
  const young = d.players.filter((p) => p.dev);
  const ch = (v, k = 2) => v == null ? '<span class="muted">-</span>' : `<b class="${v > 0.02 ? "r4" : v < -0.02 ? "r1" : ""}">${v > 0 ? "+" : ""}${v.toFixed(k)}</b>`;
  const mentorSel = (p) => p.age > 23 ? '<span class="muted small">-</span>' : `<select data-mentor="${p.player_id}"><option value="">none</option>${d.mentors.filter((m) => m.player_id !== p.player_id).map((m) =>
    `<option value="${m.player_id}"${p.dev.mentor && p.dev.mentor.player_id === m.player_id ? " selected" : ""}>${esc(m.name)} (prof ${m.professionalism}, ${m.pupils}/2)</option>`).join("")}</select>`;
  const rows = young.sort((a, b) => (b.dev.outlook - a.dev.outlook) || (a.age - b.age)).map((p) => `<tr>
      <td>${clink(p.player_id, p.name)}</td><td>${esc(p.pos)}</td><td class="num">${p.age}</td><td>${p.status === "prospect" ? '<span class="tag">minors</span>' : "NHL"}</td>
      <td class="num">${p.dev.overall.toFixed(2)}</td><td class="num">${ch(p.dev.month)}</td><td class="num">${ch(p.dev.season)}</td>
      <td class="num"><b class="${p.dev.outlook >= 1.05 ? "r4" : p.dev.outlook < 0.9 ? "r1" : ""}">x${p.dev.outlook.toFixed(2)}</b></td>
      <td class="dvfs">${devChips(p.dev.factors)}</td>
      <td>${mentorSel(p)}</td>
      <td><select data-train="${p.player_id}">${p.focus_options.map((o) => `<option${o === p.focus ? " selected" : ""}>${o}</option>`).join("")}</select></td></tr>`).join("");
  const older = d.players.filter((p) => !p.dev);
  const ints = Object.entries(d.intensities).map(([k, v]) => `<label class="dv-int${k === d.intensity ? " on" : ""}"><input type="radio" name="dv-int" value="${k}"${k === d.intensity ? " checked" : ""}>
    <b>${k}</b><span>growth x${v.growth.toFixed(2)} · injuries x${v.injuries.toFixed(2)} · ageing x${v.ageing.toFixed(2)}</span></label>`).join("");
  AFTER = () => {
    document.querySelectorAll("[data-train]").forEach((s) => (s.onchange = () => cmd(`train ${s.dataset.train} ${s.value}`)));
    document.querySelectorAll("[data-mentor]").forEach((s) => (s.onchange = () => cmd(s.value ? `mentor ${s.dataset.mentor} ${s.value}` : `mentor end ${s.dataset.mentor}`)));
    document.querySelectorAll('input[name="dv-int"]').forEach((r) => (r.onchange = () => cmd(`intensity ${r.value}`)));
  };
  return `<div class="grid">${panel("Training intensity", `<div class="dv-ints">${ints}</div>
      <p class="muted small">Hard training makes young players grow faster and costs more injuries (and veterans age a little faster); light does the opposite.</p>`)}
    ${panel(`Young players (${young.length})`, `<div class="scroll tall"><table class="dv-t"><tr><th>Player</th><th>Pos</th><th class="num">Age</th><th>Where</th><th class="num">Overall</th>
      <th class="num" title="Last monthly step">Month</th><th class="num" title="Since October">Season</th><th class="num" title="All factors multiplied: how fast he is growing now against a normal pace">Pace</th><th>What drives it</th><th>Mentor</th><th>Focus</th></tr>${rows}</table></div>
      <p class="muted small">Young players grow through the season (a step on the 1st of each month, November to April) and in the summer. Pace multiplies:
      <b>ice time</b> (23 and under in the NHL: dressing and minutes), <b>level</b> (challenged where he plays, not coasting or overmatched),
      <b>character</b> (professionalism and ambition), a <b>mentor</b> (assign one: 27+, on your NHL roster, professionalism 12+, two pupils at most),
      <b>training</b> intensity, time lost to <b>injury</b>, and your <b>coaches</b> and his <b>coachability</b>. The focus decides where the growth goes.</p>`)}
    ${older.length ? panel(`Established players (${older.length})`, `<div class="scroll">${table(older, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "pos", label: "Pos"}, {key: "age", label: "Age", num: true},
      {key: "change", label: "Change since summer", num: true, fmt: (r) => ch(r.change, 1)},
      {key: "focus", label: "Focus", fmt: (r) => `<select data-train="${r.player_id}">${r.focus_options.map((o) => `<option${o === r.focus ? " selected" : ""}>${o}</option>`).join("")}</select>`}])}</div>
      <p class="muted small">Players 27 and over change in the summer: their peak years, then decline (the body first). Professionalism slows it.</p>`) : ""}</div>`;
};

/* the player's Ratings tab: the monthly development log */
const playerV40 = VIEWS.player;
VIEWS.player = async (id) => {
  const html = await playerV40(id);
  const prev = AFTER;
  AFTER = async () => {
    if (prev) await prev();
    if ((location.hash.split("/")[2] || "") !== "ratings") return;
    const d = await api("devlog", {id}).catch(() => null);
    if (!d || !d.log.length) return;
    const rows = d.log.map((r) => `<tr><td>${esc(r.day)}</td><td>${r.kind === "summer" ? "summer" : "month"}</td><td class="num"><b class="${r.delta > 0.02 ? "r4" : r.delta < -0.02 ? "r1" : ""}">${r.delta > 0 ? "+" : ""}${r.delta.toFixed(2)}</b></td>
      <td class="dvfs">${r.factors ? devChips(r.factors) : '<span class="muted small">age and potential</span>'}</td></tr>`).join("");
    $("#view").insertAdjacentHTML("beforeend", panel("Development log", `<table class="dv-t"><tr><th>Date</th><th>Step</th><th class="num">Overall</th><th>What drove it</th></tr>${rows}</table>
      ${d.mentor ? `<p>Mentor: ${clink(d.mentor, "his mentor")}</p>` : ""}`));
    decorate($("#view"));
  };
  return html;
};

/* ================================================================ the editor and bulk import/export */
const ED = {tab: "player", pid: null, preview: null, text: ""};
const edPost = (body) => post("/api/editor", body);
function edDownload(name, text) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], {type: "text/csv"}));
  a.download = name; document.body.appendChild(a); a.click(); a.remove();
}
VIEWS.editor = async (arg) => {
  const st = await edPost({action: "state"});
  if (!st.ok) return panel("Editor", `<p>${esc(st.output)}</p>`);
  const tabs = `<div class="tabs">${[["player", "Players"], ["clubs", "Clubs"], ["bulk", "Import / Export"]].map(([k, l]) =>
    `<a class="btn${ED.tab === k ? " active" : ""}" data-edtab="${k}">${l}</a>`).join(" ")}<span class="spacer"></span>
    ${st.edited ? `<span class="tag warn" title="Edited saves are marked for good">edited save since ${esc(st.edited)}</span>` : ""}
    <button id="ed-mode" class="${st.enabled ? "" : "primary"}">${st.enabled ? "Turn commissioner mode off" : "Turn commissioner mode on"}</button></div>`;
  AFTER = () => {
    document.querySelectorAll("[data-edtab]").forEach((a) => a.onclick = () => { ED.tab = a.dataset.edtab; render(); });
    $("#ed-mode").onclick = async () => {
      if (!st.enabled && !(await ask("Turn on commissioner mode? You can edit anything, and this save is marked as edited for good."))) return;
      await edPost({action: "enable", on: !st.enabled}); render();
    };
    if (ED.after) ED.after();
  };
  ED.after = null;
  if (!st.enabled) return tabs + panel("Editor", `<p>The editor changes players, contracts and clubs, and imports changes in bulk from a spreadsheet (CSV).
    It needs commissioner mode; a save that has used it is marked as edited.</p><p class="muted">Exporting is always allowed:</p>${edBulk(false)}`);
  if (ED.tab === "clubs") return tabs + await edClubs();
  if (ED.tab === "bulk") return tabs + edBulk(true);
  return tabs + await edPlayer(arg ? +arg : ED.pid);
};
async function edPlayer(pid) {
  ED.pid = pid || ED.pid;
  const search = `<div class="toolbar"><input id="ed-q" placeholder="Find a player to edit" style="width:280px" autocomplete="off"><div id="ed-res" class="mb-results" hidden></div></div>`;
  ED.after = () => {
    let t = null;
    $("#ed-q").oninput = () => { clearTimeout(t); const q = $("#ed-q").value.trim(); if (q.length < 2) return; t = setTimeout(async () => {
      const d = await api("search", {q}); const box = $("#ed-res");
      box.innerHTML = d.players.map((p) => `<a data-edp="${p.player_id}">${esc(p.pos)} ${esc(p.name)} <span class="muted">${esc(p.team || p.status)}</span></a>`).join("") || '<div class="muted">Nobody.</div>';
      box.hidden = false; box.querySelectorAll("[data-edp]").forEach((a) => a.onclick = () => { ED.pid = +a.dataset.edp; render(); });
    }, 160); };
    const save = $("#ed-save");
    if (save) save.onclick = async () => {
      const changes = {};
      document.querySelectorAll("[data-edf]").forEach((x) => { if (x.value !== x.dataset.was) changes[x.dataset.edf] = x.value; });
      if (!Object.keys(changes).length) return toast("Nothing changed.");
      const r = await edPost({action: "save", player_id: ED.pid, changes});
      toast(r.output, !r.ok); if (r.ok) render();
    };
  };
  if (!ED.pid) return search + panel("Edit a player", '<p class="muted">Search for a player above, or open a player and press Edit.</p>');
  const r = await edPost({action: "form", player_id: ED.pid});
  if (!r.ok) return search + panel("Edit a player", `<p>${esc(r.output)}</p>`);
  const f = r.form;
  const inp = (k, v, w = 70) => `<input data-edf="${k}" data-was="${v ?? ""}" value="${esc(String(v ?? ""))}" style="width:${w}px">`;
  const lab = (k) => esc(k.replace(/_/g, " ").replace(/^pos /, "position ").replace(/^role /, "role "));
  const grid = (obj, keys, w) => `<div class="ed-grid">${keys.map((k) => `<label><span>${lab(k)}</span>${inp(k, obj[k], w)}</label>`).join("")}</div>`;
  const ratings = Object.entries(f.groups).map(([g, keys]) => panel(g[0].toUpperCase() + g.slice(1), grid(f.ratings, keys, 52))).join("");
  return search + `<div class="grid">${panel(`${esc(f.bio.first_name)} ${esc(f.bio.last_name)}`, `${grid(f.bio, Object.keys(f.bio), 110)}
      <div class="ed-grid"><label><span>club (abbr, FA)</span>${inp("team", f.team, 70)}</label><label><span>status (active / prospect)</span>${inp("status", f.status, 90)}</label>
      <label><span>potential (1-20)</span>${inp("potential", f.potential, 60)}</label></div>
      <div class="ed-grid"><label><span>cap hit</span>${inp("cap_hit", f.contract ? f.contract.cap_hit : "", 100)}</label><label><span>contract ends (season)</span>${inp("contract_end", f.contract ? f.contract.contract_end : "", 70)}</label>
      <label><span>clause (none, NTC, NMC, MNTC:10)</span>${inp("clause", f.clause, 90)}</label></div>
      <p><button class="primary" id="ed-save">Save changes</button> <a class="btn" href="#player/${f.player_id}">His page</a></p>
      <p class="muted small">Ratings 1-20, abilities 1-200; the match engine's attributes are re-derived from the ratings when you save.</p>`)}
    ${panel("Personality", grid(f.personality, Object.keys(f.personality), 52))}${f.career ? panel("NHL career before this save", grid(f.career, Object.keys(f.career), 60) + '<p class="muted small">Games, goals, assists, wins, shutouts, playoff games and seasons from before the first season on file; added to his career everywhere (waivers, milestones, Hall of Fame, all-time leaders).</p>') : ""}${ratings}</div>`;
}
async function edClubs() {
  const r = await edPost({action: "clubs"});
  ED.after = () => document.querySelectorAll("[data-edclub]").forEach((b) => b.onclick = async () => {
    const tr = b.closest("tr"), changes = {};
    tr.querySelectorAll("input").forEach((x) => { if (x.value !== x.dataset.was) changes[x.name] = x.value; });
    const res = await edPost({action: "club", team_id: +b.dataset.edclub, changes}); toast(res.output, !res.ok);
  });
  const cell = (c, k, w) => `<td><input name="${k}" data-was="${esc(c[k] || "")}" value="${esc(c[k] || "")}" style="width:${w}px"></td>`;
  return panel("Clubs", `<table class="dv-t"><tr><th>Abbr</th><th>City / name</th><th>Nickname</th><th>Conference</th><th>Division</th><th></th></tr>${r.clubs.map((c) =>
    `<tr>${cell(c, "abbr", 50)}${cell(c, "name", 150)}${cell(c, "nickname", 120)}${cell(c, "conference", 90)}${cell(c, "division", 100)}<td><button class="mini" data-edclub="${c.team_id}">Save</button></td></tr>`).join("")}</table>`);
}
function edBulk(on) {
  ED.after = ED.after || (() => {});
  const prevAfter = ED.after;
  ED.after = () => {
    prevAfter();
    document.querySelectorAll("[data-exp]").forEach((b) => b.onclick = async () => {
      const r = await edPost({action: "export", scope: b.dataset.exp});
      if (!r.ok) return toast(r.output, true);
      edDownload(`players_${b.dataset.exp}.csv`, r.csv);
    });
    const file = $("#ed-file");
    if (file) file.onchange = async () => {
      const f = file.files[0]; if (!f) return;
      ED.text = await f.text();
      const r = await edPost({action: "import", text: ED.text, apply: false});
      ED.preview = r.ok ? r.result : {errors: [{row: "-", error: r.output}], changes: [], rows: 0, matched: 0, created: 0, unknown_columns: []};
      render();
    };
    const go = $("#ed-apply");
    if (go) go.onclick = async () => {
      if (!(await ask(`Apply ${ED.preview.changes.length} changes${ED.preview.errors.length ? ` (${ED.preview.errors.length} rows with problems are skipped)` : ""}?`))) return;
      const r = await edPost({action: "import", text: ED.text, apply: true});
      toast(r.ok ? `Applied: ${r.result.changes.length} players changed or created.` : r.output, !r.ok);
      ED.preview = null; render();
    };
  };
  const p = ED.preview;
  const prev = p ? `<h4>Preview</h4><p>${p.rows} rows: ${p.matched} matched, ${p.created} new, ${p.changes.length} with changes, ${p.errors.length} with problems.
      ${p.unknown_columns.length ? `<br><span class="muted">Columns ignored: ${p.unknown_columns.map(esc).join(", ")}</span>` : ""}</p>
    ${p.errors.length ? `<table class="dv-t"><tr><th>Row</th><th>Problem</th></tr>${p.errors.slice(0, 60).map((e) => `<tr><td>${e.row}</td><td class="neg">${esc(e.error)}</td></tr>`).join("")}</table>` : ""}
    ${p.changes.length ? `<div class="scroll"><table class="dv-t"><tr><th>Row</th><th>Player</th><th>Changes</th></tr>${p.changes.slice(0, 200).map((c) =>
      `<tr><td>${c.row}</td><td>${esc(c.name)}</td><td class="dvfs">${c.fields.map(esc).join("; ")}</td></tr>`).join("")}</table></div>` : ""}
    <p><button class="primary" id="ed-apply"${p.changes.length ? "" : " disabled"}>Apply the changes</button></p>` : "";
  return panel("Export", `<p>Every player's bio, club, ratings, personality, potential and contract as a spreadsheet (CSV). Edit it in Excel or LibreOffice and import it back.</p>
      <p><button data-exp="mine">Your organisation</button> <button data-exp="nhl">The NHL</button> <button data-exp="all">Everyone</button></p>`)
    + (on ? panel("Import", `<p>A CSV with any of the export's columns. Rows match by <code>player_id</code>, or by first name, last name and birth date; a row that matches nobody and has a name, birth date and position creates a new player.
      Common headers work too (CA, PA, DOB, surname, club, salary). You see every change and every problem before anything is written.</p>
      <p><input type="file" id="ed-file" accept=".csv,text/csv"></p>${prev}`) : "");
}
(() => {
  const file = MENUS[0][1];
  const at = file.findIndex((x) => Array.isArray(x) && x[0] === "Import Database...");
  file.splice(at >= 0 ? at + 1 : 2, 0, ["Editor...", "#editor"]);
  SCREEN_NAMES.editor = "Editor";
})();
const playerEd40 = VIEWS.player;
VIEWS.player = async (id) => {
  const html = await playerEd40(id);
  const st = await edPost({action: "state"}).catch(() => ({}));
  return st.enabled ? html.replace('<div class="toolbar">', `<div class="toolbar"><a class="btn" href="#editor/${id}">Edit (editor)</a>`) : html;
};

/* ---- boot (keep last) ---- */
// boot moved to v41.js
