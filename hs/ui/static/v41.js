/* v41: contract structure in talks, the contract's season-by-season pay, conditional picks, career history. */

/* ================================================================ contract talks: structure */
Talks.structure = "flat";
const talksRenderV41 = Talks.render.bind(Talks);
Talks.render = function (v) {
  if (v && v.open && v.structures && v.clause_asks) {
    const d = (v.structures[this.structure] || {}).discount || 0;
    if (d) {
      v = Object.assign({}, v, {_raw: v._raw || v});
      const cut = (o) => Object.fromEntries(Object.entries(o).map(([y, a]) => [y, Math.round(a * (1 - d))]));
      v.clause_asks = Object.fromEntries(Object.entries(v.clause_asks).map(([c, o]) => [c, cut(o)]));
      v.asks = cut(v.asks);
      if (v.asks_ntc) v.asks_ntc = cut(v.asks_ntc);
    }
  }
  talksRenderV41(v);
  if (!v || !v.open || !v.structures) return;
  const anchor = document.querySelector(".tk-clause") || document.querySelector(".tk-offer .row");
  if (!anchor) return;
  const opts = Object.entries(v.structures).map(([k, s]) => `<option value="${k}"${k === this.structure ? " selected" : ""}>${esc(s.label)}${s.discount ? ` (asks ${(s.discount * 100).toFixed(1)}% less)` : ""}</option>`).join("");
  anchor.insertAdjacentHTML("afterend", `<div class="tk-structure"><label>Structure <select id="tk-structure">${opts}</select></label>
    <span class="muted small">same cap hit; front-loading and signing bonuses pay him earlier, so he takes a little less, but they cost you more cash up front</span></div>`);
  $("#tk-structure").onchange = (e) => { this.structure = e.target.value; this.render(v._raw || v); };
};
Talks.send = async function () {
  const box = $("#tk-log");
  const prot = this.clause && this.clause !== "none" ? this.clause : "";
  const st = this.structure && this.structure !== "flat" ? this.structure : "";
  box.insertAdjacentHTML("beforeend", `<div class="bub you"><div class="who">You</div>${this.years} yr x ${mil(this.aav)}${st === "front" ? ", front-loaded" : st === "bonus" ? ", bonus-heavy" : ""}${prot ? " with trade protection" : ""}</div><div class="bub agent typing"><i></i><i></i><i></i></div>`);
  box.scrollTop = box.scrollHeight;
  document.querySelectorAll(".tk-offer button").forEach((b) => b.disabled = true);
  const r = await quietCmd(`propose ${this.pid} ${Math.round(this.aav)} ${this.years}${st ? " " + st : ""}${prot ? " " + prot : ""}`);
  await new Promise((res) => setTimeout(res, 650));
  if (!r.ok) toast(r.output, true);
  this.render(await api("negotiation", {id: this.pid}));
};

/* ================================================================ the player's Contract tab: pay by season */
const playerV41 = VIEWS.player;
VIEWS.player = async (id) => {
  const html = await playerV41(id);
  const prev = AFTER;
  AFTER = async () => {
    if (prev) await prev();
    if ((location.hash.split("/")[2] || "") !== "contract") return;
    const p = await api("player", {id}).catch(() => null);
    if (!p || !p.pay || !p.pay.length) return;
    const cap = p.contract ? p.contract.cap_hit : null;
    const label = {flat: "flat", front: "front-loaded", bonus: "front-loaded, signing bonuses on 1 July"}[p.pay_structure] || p.pay_structure;
    const rows = p.pay.map((y) => `<tr><td>${ssn(y.season)}</td><td class="num">${cap ? mil(cap) : ""}</td><td class="num">${mil(y.salary)}</td><td class="num">${y.bonus ? mil(y.bonus) : "-"}</td><td class="num"><b>${mil(y.cash)}</b></td></tr>`).join("");
    $("#view").insertAdjacentHTML("beforeend", panel("Pay by season",
      `<p class="muted small">Structure: ${esc(label)}</p><table class="pay-t"><tr><th>Season</th><th class="num">Cap hit</th><th class="num">Salary</th><th class="num">Signing bonus</th><th class="num">Cash</th></tr>${rows}</table>
       <p class="muted small">The cap counts the average every season; the club pays the cash column.</p>`));
  };
  return html;
};

/* ================================================================ the trade screen: conditional picks */
/* v42 (register v39 #7): "Trade for him" opens the trade screen with him already ticked */
let TRADE_WANT = null;
const tradeV41 = VIEWS.trade;
VIEWS.trade = async (team) => {
  const html = await tradeV41(team);
  const d = await api("trade", team ? {team} : {});
  const mine = {};
  if (d.mine) d.mine.picks.forEach((p) => (mine[p.key] = p));
  const prev = AFTER;
  AFTER = async () => {
    if (prev) await prev();
    if (TRADE_WANT) {
      const x = document.querySelector(`input.tr-a[data-side="get"][value="player:${TRADE_WANT}"]`);
      TRADE_WANT = null;
      if (x && !x.checked && !x.disabled) {
        x.checked = true; x.dispatchEvent(new Event("change", {bubbles: true}));
        const row = x.closest("tr"); if (row) row.scrollIntoView({block: "center"});
      }
    }
    document.querySelectorAll('.tp-pk input.tr-a[data-side="give"]').forEach((x) => {
      const p = mine[x.value];
      if (!p || !p.cond_values || !Object.keys(p.cond_values).length) return;
      const lab = x.closest("label");
      const opts = Object.keys(p.cond_values).map((k) => `<option value="${k}">${k.startsWith("cpo") ? "up if playoffs" : "up if we win a round"}</option>`).join("");
      lab.insertAdjacentHTML("afterend", `<select class="tp-cond" data-for="${x.value}" title="Conditional: it becomes your pick one round higher if the condition comes true this season (that pick is held until the draft)"><option value="">no cond.</option>${opts}</select>`);
    });
    document.querySelectorAll(".tp-cond").forEach((s) => s.onchange = () => {
      const base = s.dataset.for;
      const box = s.previousElementSibling.querySelector("input");
      const p = mine[base] || {};
      box.value = s.value ? `${base}:${s.value}` : base;
      const up = ["", "1st", "2nd", "3rd", "4th", "5th", "6th"][p.round - 1] || "";
      box.dataset.name = (p.label || box.dataset.name).replace(/ \(becomes a .*\)$/, "") + (s.value ? ` (becomes a ${up} if ${s.value.startsWith("cpo") ? "we make the playoffs" : "we win a round"})` : "");
      box.dataset.val = s.value ? String(Math.round(p.cond_values[s.value])) : String(Math.round(p.value || 0));
      s.previousElementSibling.querySelector(".v").textContent = box.dataset.val;
      if (!box.checked) box.checked = true;
      box.dispatchEvent(new Event("change", {bubbles: true}));
    });
  };
  return html;
};

/* ================================================================ the editor's Import / Export tab: career history and past drafts */
const edBulkV41 = edBulk;
const HX = {career: null, drafts: null, seasons: null, text: {}};
edBulk = function (on) {
  const html = edBulkV41(on);
  const prevAfter = ED.after;
  ED.after = () => {
    if (prevAfter) prevAfter();
    [["career", "career_import"], ["drafts", "drafts_import"], ["seasons", "seasons_import"]].forEach(([k, act]) => {
      const f = $(`#hx-${k}`);
      if (f) f.onchange = async () => {
        const file = f.files[0]; if (!file) return;
        HX.text[k] = await file.text();
        const r = await edPost({action: act, text: HX.text[k], apply: false});
        HX[k] = r.ok ? r.result : {error: r.output};
        render();
      };
      const b = $(`#hx-${k}-go`);
      if (k === "career") {
        const rd = $("#hx-db-read"), go = $("#hx-db-go");
        const args = () => ({db_file: $("#hx-db-file").value, export_folder: $("#hx-db-folder").value});
        if (rd) rd.onclick = async () => {
          rd.disabled = true; rd.textContent = "Reading...";
          const r = await edPost(Object.assign({action: "history_db", apply: false}, args()));
          HX.db = r.ok ? Object.assign(r.result, args()) : {error: r.output}; render();
        };
        if (go) go.onclick = async () => {
          go.disabled = true; go.textContent = "Importing...";
          const r = await edPost({action: "history_db", apply: true, db_file: HX.db.db_file, export_folder: HX.db.export_folder});
          toast(r.ok ? `Imported ${(r.result.skater_lines + r.result.goalie_lines).toLocaleString()} career lines and ${r.result.draft_picks_added.toLocaleString()} draft picks.` : r.output, !r.ok);
          HX.db = null; render();
        };
      }
      if (b) b.onclick = async () => {
        const r = await edPost({action: act, text: HX.text[k], apply: true});
        toast(r.ok ? "Imported." : r.output, !r.ok);
        HX[k] = null; render();
      };
    });
  };
  const c = HX.career, d = HX.drafts, sv = HX.seasons;
  const sprev = sv ? (sv.error ? `<p class="neg">${esc(sv.error)}</p>` : `<p>${sv.rows} rows: <b>${sv.seasons}</b> season lines for ${sv.players} players, ${sv.errors.length} with problems${sv.unknown_teams.length ? `; clubs not in this world (kept without a club): ${sv.unknown_teams.slice(0, 12).map(esc).join(", ")}` : ""}.</p>
      ${sv.errors.length ? `<table class="dv-t"><tr><th>Row</th><th>Problem</th></tr>${sv.errors.slice(0, 40).map((e) => `<tr><td>${e.row}</td><td class="neg">${esc(e.error)}</td></tr>`).join("")}</table>` : ""}
      <p><button class="primary" id="hx-seasons-go"${sv.seasons ? "" : " disabled"}>Import ${sv.seasons} season lines</button></p>`) : "";
  const cprev = c ? (c.error ? `<p class="neg">${esc(c.error)}</p>` : `<p>${c.rows} profiles, ${c.with_nhl} with NHL games: <b>${c.matched}</b> match players in this world${c.skipped_recorded ? `, ${c.skipped_recorded} already have seasons on file (left alone)` : ""}, ${c.unmatched.length} not found.</p>
      ${c.unmatched.length ? `<p class="muted small">Not found: ${c.unmatched.slice(0, 30).map(esc).join(", ")}${c.unmatched.length > 30 ? " ..." : ""}</p>` : ""}
      <p><button class="primary" id="hx-career-go"${c.matched ? "" : " disabled"}>Import ${c.matched} careers</button></p>`) : "";
  const dprev = d ? (d.error ? `<p class="neg">${esc(d.error)}</p>` : `<p>${d.rows} rows (${d.years.join(", ") || "no years"}): <b>${d.linked}</b> linked to players in this world, ${d.named} kept by name, ${d.skipped} already on file, ${d.errors.length} with problems.</p>
      ${d.errors.length ? `<table class="dv-t"><tr><th>Row</th><th>Problem</th></tr>${d.errors.slice(0, 40).map((e) => `<tr><td>${e.row}</td><td class="neg">${esc(e.error)}</td></tr>`).join("")}</table>` : ""}
      <p><button class="primary" id="hx-drafts-go"${d.linked + d.named ? "" : " disabled"}>Import ${d.linked + d.named} picks</button></p>`) : "";
  const db = HX.db;
  const dbprev = db ? (db.error ? `<p class="neg">${esc(db.error)}</p>` : `<p><b>${(db.skater_lines + db.goalie_lines).toLocaleString()}</b> career lines (${db.players.toLocaleString()} players, ${db.nhl_players.toLocaleString()} with NHL seasons) and <b>${db.draft_picks.toLocaleString()}</b> NHL draft picks (${db.draft_years[0] || "-"}-${db.draft_years[db.draft_years.length - 1] || "-"}). Importing again replaces the earlier import.</p>
      <p><button class="primary" id="hx-db-go">Import them</button></p>`) : "";
  return html + panel("History before this save", `<p>A world built from a database export starts with no seasons on file. Bring the past in:</p>
      <h4>From the database file (best)</h4><p class="muted small">Every player's career season by season, in every league (clubs and leagues outside this world keep their names), and every NHL Entry Draft pick, read from your <code>database.db</code>, with the export folder you built the world from (for the ids). Seasons before this save's first season only.</p>
      <table class="kvt"><tr><th>Database file</th><td><input id="hx-db-file" size="60" placeholder="C:\\HockeyData\\database.db" value="${esc((db && db.db_file) || "")}"></td></tr>
      <tr><th>Export folder</th><td><input id="hx-db-folder" size="60" placeholder="C:\\HockeyData\\Export" value="${esc((db && db.export_folder) || "")}"></td></tr></table>
      <p><button id="hx-db-read">Read the file</button></p>${dbprev}
      <h4>Careers (M3 player profiles)</h4><p class="muted small">The <code>player_profiles_plain_english_m311.csv</code> export: NHL games and seasons for the players it covers, matched by name and birth date. For goals, assists and the rest, use the career columns in the player CSV above.</p>
      <p><input type="file" id="hx-career" accept=".csv,text/csv"></p>${cprev}
      <h4>Past seasons, line by line</h4><p class="muted small">A CSV with <code>player_id</code> (or <code>player</code> and <code>birth_date</code>), <code>season, league, team, gp, g, a, pim</code> (goalies: <code>gp, w, l, otl, so, ga, sa</code>), optional <code>split</code> (RS or PO). The lines go on file like seasons the game played: his Career stats, the leaders, waivers, milestones and the Hall of Fame. A player given NHL seasons this way drops his games-only total above, so nothing counts twice.</p>
      <p><input type="file" id="hx-seasons" accept=".csv,text/csv"></p>${sprev}
      <h4>Past drafts</h4><p class="muted small">A CSV with <code>draft_year, round, overall, team, player</code> (optionally <code>player_id</code> or <code>birth_date</code>). Players in this world are linked; others keep their name on the Past Drafts screen. Drafts the game held itself are not touched.</p>
      <p><input type="file" id="hx-drafts" accept=".csv,text/csv"></p>${dprev}`);
};

/* ================================================================ the player's Career stats tab: before this save */
const playerV41b = VIEWS.player;
VIEWS.player = async (id) => {
  const html = await playerV41b(id);
  const prev = AFTER;
  AFTER = async () => {
    if (prev) await prev();
    if ((location.hash.split("/")[2] || "") !== "stats") return;
    const p = await api("player", {id}).catch(() => null);
    const c = p && p.career_prior;
    if (!c) return;
    const goalie = p.position === "G";
    $("#view").insertAdjacentHTML("beforeend", panel("NHL career before this save", `<dl class="kv"><dt>Seasons</dt><dd>${c.seasons}</dd><dt>Games</dt><dd>${c.gp}</dd>
      ${goalie ? `<dt>Wins</dt><dd>${c.w || "-"}</dd><dt>Shutouts</dt><dd>${c.so || "-"}</dd>` : `<dt>Goals</dt><dd>${c.g || "-"}</dd><dt>Assists</dt><dd>${c.a || "-"}</dd><dt>Points</dt><dd>${(c.g + c.a) || "-"}</dd>`}
      ${c.po_gp ? `<dt>Playoff games</dt><dd>${c.po_gp}</dd>` : ""}</dl><p class="muted small">From ${c.source === "m3" ? "the database export's profiles (games and seasons only)" : "the editor"}; counted in his career totals, the waiver rules, milestones and the Hall of Fame.</p>`));
  };
  return html;
};

/* ================================================================ league history: all-time with careers before the save */
const lhViewV41 = LeagueHistory.view.bind(LeagueHistory);
LeagueHistory.view = async function () {
  let html = await lhViewV41();
  const d = await api("leaguehistory");
  if (d.prior) html = html.replace(/All-time NHL points \(seasons on file, since [^)]*\)/, "All-time NHL points (seasons on file plus careers before this save)");
  if (d.games && d.games.length) {
    html += panel("Most NHL games", `<div class="scroll">${table(d.games, [{key: "rk", label: "#", num: 1, fmt: (r) => d.games.indexOf(r) + 1},
      {key: "name", label: "Player", fmt: (r) => plink(r.player_id, r.name) + (r.active ? "" : ' <span class="muted">retired</span>')}, {key: "pos", label: "Pos"},
      {key: "seasons", label: "Seasons", num: 1}, {key: "gp", label: "GP", num: 1}])}</div>`);
  }
  return html;
};

/* ---- boot moved to v44.js ---- */
