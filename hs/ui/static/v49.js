/* v49: player pictures (your photos, or the back of his jersey with name and number) and jersey numbers
   (change on the player screen and the roster; retired numbers on the team page) (docs/NUMBERS.md). */

let FACE_V = 1;
const portraitV49 = portrait;
portrait = function (seed, abbr, pos, size = 84) {
  if (/^\d+$/.test(String(seed))) {
    return `<img class="face-img" src="/face/${seed}?v=${FACE_V}" width="${size}" height="${size}" alt="" loading="lazy">`;
  }
  return portraitV49(seed, abbr, pos, size);
};

async function changeNumber(pid, cur) {
  const n = await ask(`New number (1-98)${cur ? `; he wears #${cur} now` : ""}:`, {ok: "Change", input: cur ? String(cur) : ""});
  if (!n) return;
  let r = await post("/api/command", {line: `number ${pid} ${n}`});
  if (!r.ok && /Swap numbers/.test(r.output || "")) {
    if (await ask(r.output.replace(/^Error: /, "") + " Swap?", {ok: "Swap"})) r = await post("/api/command", {line: `number ${pid} ${n} swap`});
    else return;
  }
  toast(r.output.replace(/^Error: /, ""), !r.ok);
  if (r.ok) { FACE_V++; render(); }
}

document.addEventListener("click", (e) => {
  const a = e.target.closest && e.target.closest(".jn, .pp-numbtn");
  if (!a) return;
  e.preventDefault();
  changeNumber(a.dataset.pid, a.dataset.num);
});

const playerV49 = VIEWS.player;
VIEWS.player = async (id) => {
  const html = await playerV49(id);
  const p = await api("player", {id});
  const num = p.jersey_number;
  const canEdit = p.mine || (STATE && STATE.commissioner);
  const badge = `<span class="pp-num">${num != null ? "#" + num : ""}</span>`;
  const btn = canEdit && p.team_id ? ` <a class="btn small pp-numbtn" data-pid="${p.player_id}" data-num="${num ?? ""}">Change number</a>` : "";
  return html.replace('<div class="pp-name">', `<div class="pp-name">${badge}`).replace(/(<div class="pp-name">[\s\S]*?<\/div>)/, `$1${btn ? `<div class="pp-numrow">${btn}</div>` : ""}`);
};

/* the team page: retired numbers (and retire one at your club) */
const teamV49 = VIEWS.team;
if (teamV49) {
  VIEWS.team = async (...args) => {
    const html = await teamV49(...args);
    const id = location.hash.slice(1).split("/")[1] || "";
    if (!/^\d+$/.test(id)) return html;
    let d;
    try { d = await api("retirednumbers", {team: id}); } catch (e) { return html; }
    const mine = STATE && +id === STATE.team_id;
    const list = d.numbers.length ? d.numbers.map((r) => `<span class="rn-chip"><b>#${r.number}</b> ${r.player_id ? clink(r.player_id, r.name) : esc(r.name)}${r.season ? ` <span class="muted">${ssn(r.season)}</span>` : ""}</span>`).join(" ") : '<span class="muted">None yet.</span>';
    const form = mine ? `<div class="row rn-form"><input id="rn-num" size="4" placeholder="#"> <input id="rn-who" size="22" placeholder="player (name or id)"> <button id="rn-go">Retire the number</button>
      <span class="muted small">for a player with ${d.games}+ games for the club, or a Hall of Famer</span></div>` : "";
    const extra = panel("Retired numbers", `<p>${list} <span class="muted small">· #99 is retired league-wide</span></p>${form}`);
    const prev = AFTER;
    AFTER = () => {
      if (prev) prev();
      const b = $("#rn-go");
      if (b) b.onclick = async () => { const r = await cmd(`number retire ${$("#rn-num").value} ${$("#rn-who").value}`); if (r.ok) render(); };
    };
    return html + extra;
  };
}

/* File > Player Photos... */
const Faces = {
  open() {
    Modal.open(`<h3>Player photos</h3><p>Put photo files named by a player's id (12345.png, 12345.jpg, 12345.webp; up to 2 MB each) in the <code>faces</code> folder next to your saves,
      or import a folder of them here. A player with no photo is shown as the back of his jersey, with his name and number in his club's colours.</p>
      <div class="row"><input id="fc-path" placeholder="A folder of photos" size="48"><button class="primary" id="fc-go">Import</button></div>`, "faces");
    $("#fc-go").onclick = async () => {
      try { const r = await post("/api/save", {action: "faces", path: $("#fc-path").value}); toast(r.output); FACE_V++; Modal.close(); render(); }
      catch (e) { toast(e.message, true); }
    };
  },
};
(() => {
  const file = MENUS.find((m) => m[0] === "File")[1];
  const i = file.findIndex((it) => it !== "-" && it[0] === "Logos...");
  file.splice(i + 1, 0, ["Player Photos...", () => Faces.open()]);
})();

