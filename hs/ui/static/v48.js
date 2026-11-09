/* v48: your own club logos (File > Logos...), quickstarts (File > Save as Quickstart...) and schedule export/import
   (League > Commissioner) (docs/QUICKSTARTS.md). */

let LOGOS = new Set();
let LOGO_V = 1;
const crestV48 = crest;
crest = function (abbr, size = 18) {
  if (abbr && LOGOS.has(String(abbr).toUpperCase())) {
    return `<img class="crest crest-img" src="/logo/${encodeURIComponent(String(abbr).toUpperCase())}?v=${LOGO_V}" width="${size}" height="${Math.round(size * 1.12)}" alt="" onerror="this.outerHTML=''">`;
  }
  return crestV48(abbr, size);
};
async function loadLogos() {
  try { const r = await fetch("/api/logos"); const d = await r.json(); LOGOS = new Set(d.logos || []); return d; } catch (e) { return {logos: [], folders: []}; }
}

const Logos = {
  async open() {
    const d = await loadLogos();
    Modal.open(`<h3>Club logos</h3><p>Put image files named by a club's abbreviation (MTL.png, TOR.svg, HOU.webp; up to 2 MB each) in a logos folder, or import a folder of them here.
      They replace the generated crests everywhere; clubs without a file keep theirs.</p>
      <p class="muted small">Logos folders: ${d.folders.map((f) => `<code>${esc(f)}</code>`).join(", ") || "none (start the game with a saves folder)"}</p>
      <p>${d.logos.length ? `${d.logos.length} logo(s): ${d.logos.map((a) => `<span class="lg-chip">${crest(a, 22)} ${esc(a)}</span>`).join(" ")}` : '<span class="muted">No logos yet.</span>'}</p>
      <div class="row"><input id="lg-path" placeholder="A folder of logo files" size="48"><button class="primary" id="lg-go">Import</button></div>`, "logos");
    $("#lg-go").onclick = async () => {
      try { const r = await post("/api/save", {action: "logos", path: $("#lg-path").value}); toast(r.output); LOGO_V++; await loadLogos(); Modal.close(); render(); }
      catch (e) { toast(e.message, true); }
    };
  },
};

async function saveQuickstart() {
  const name = await ask("Save this world as a quickstart? New careers can start from it with any club. (Only at the start of a season: after the pre-season phase, before the first game.)",
    {ok: "Save quickstart", input: `${STATE && STATE.season ? STATE.season : ""} quickstart`.trim()});
  if (!name) return;
  try { const r = await post("/api/save", {action: "quickstart", name}); toast(r.output); } catch (e) { toast(e.message, true); }
}

/* the Commissioner screen gets a schedule panel (export for anyone, import in commissioner mode) */
const commishV48 = VIEWS.commish;
VIEWS.commish = async (...args) => {
  const html = await commishV48(...args);
  const prev = AFTER;
  const st = await post("/api/editor", {action: "state"}).catch(() => ({enabled: false}));
  const sched = panel("Schedule", `<p>Export this season's regular-season schedule as a CSV (date, home, away; scores for games played).
      ${st.enabled ? "Import a CSV with date, home and away columns to replace the games not yet played (preview first)." : "Importing one needs commissioner mode."}</p>
    <div class="row"><button id="sc-exp">Export schedule</button>${st.enabled ? ` <input type="file" id="sc-file" accept=".csv,text/csv"> <button id="sc-prev">Preview import</button> <button class="primary" id="sc-apply" disabled>Apply</button>` : ""}</div>
    <div id="sc-out"></div>`);
  AFTER = () => {
    if (prev) prev();
    $("#sc-exp").onclick = async () => {
      const r = await post("/api/editor", {action: "schedule_export"});
      if (!r.ok) return toast(r.output, true);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([r.csv], {type: "text/csv"}));
      a.download = `schedule_${(STATE && STATE.season) || "season"}.csv`;
      document.body.appendChild(a); a.click(); a.remove();
    };
    let text = "";
    const show = (res) => {
      const ok = !res.problems.length;
      $("#sc-out").innerHTML = `<p>${res.rows} row(s), ${res.games || 0} game(s) ready${res.applied ? `; <b>${res.applied} imported</b>` : ""}.</p>
        ${res.problems.length ? `<ul class="xp-warn">${res.problems.slice(0, 20).map(([k, t]) => `<li>row ${k}: ${esc(t)}</li>`).join("")}${res.problems.length > 20 ? `<li>... ${res.problems.length - 20} more</li>` : ""}</ul>` : ""}
        ${res.warnings.map((w) => `<p class="muted">${esc(w)}</p>`).join("")}`;
      const b = $("#sc-apply"); if (b) b.disabled = !ok || !!res.applied;
    };
    const f = $("#sc-file");
    if (f) f.onchange = async () => { text = f.files[0] ? await f.files[0].text() : ""; $("#sc-apply").disabled = true; };
    const pv = $("#sc-prev");
    if (pv) pv.onclick = async () => { if (!text) return toast("Choose a CSV file.", true); const r = await post("/api/editor", {action: "schedule_import", text}); r.ok ? show(r.result) : toast(r.output, true); };
    const ap = $("#sc-apply");
    if (ap) ap.onclick = async () => {
      if (!(await ask("Replace the season's unplayed games with this schedule?", {ok: "Replace"}))) return;
      const r = await post("/api/editor", {action: "schedule_import", text, apply: true}); r.ok ? show(r.result) : toast(r.output, true);
    };
  };
  return html + sched;
};

(() => {
  const file = MENUS.find((m) => m[0] === "File")[1];
  const i = file.findIndex((it) => it !== "-" && it[0] === "Save Game As...");
  file.splice(i + 1, 0, ["Save as Quickstart...", () => saveQuickstart()], ["Logos...", () => Logos.open()]);
})();

