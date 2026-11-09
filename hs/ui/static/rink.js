"use strict";
// v30: the 2D game view (hs/sim/rink2d.py tracking). Every skater, both goalies and the puck at 5 frames a second,
// interpolated to 60 in the browser; the puck carrier ringed; passes and shots as the puck moves; the score, the
// clock, who is on the ice. Falls back to the old event replay (replay.js) if the tracking cannot be built.
const Rink = (() => {
  const W = 200, H = 85;
  function draw(ctx, cw, ch) {
    const sx = cw / W, sy = ch / H, X = (x) => (x + 100) * sx, Y = (y) => (42.5 - y) * sy;
    ctx.clearRect(0, 0, cw, ch);
    ctx.fillStyle = "#f6f9fc"; ctx.strokeStyle = "#7c8ea6"; ctx.lineWidth = 2;
    const r = 28 * sx;
    const boards = () => { ctx.beginPath(); ctx.moveTo(r, 1); ctx.lineTo(cw - r, 1); ctx.quadraticCurveTo(cw - 1, 1, cw - 1, r); ctx.lineTo(cw - 1, ch - r);
      ctx.quadraticCurveTo(cw - 1, ch - 1, cw - r, ch - 1); ctx.lineTo(r, ch - 1); ctx.quadraticCurveTo(1, ch - 1, 1, ch - r); ctx.lineTo(1, r); ctx.quadraticCurveTo(1, 1, r, 1); };
    boards(); ctx.fill(); ctx.stroke();
    ctx.save(); boards(); ctx.clip();                     // v39 (#1): the goal lines stop at the boards in the corners
    const line = (x, c, w) => { ctx.strokeStyle = c; ctx.lineWidth = w; ctx.beginPath(); ctx.moveTo(X(x), 2); ctx.lineTo(X(x), ch - 2); ctx.stroke(); };
    line(0, "#c8102e", 3 * sx); line(25, "#1f4fa3", 3 * sx); line(-25, "#1f4fa3", 3 * sx); line(89, "#c8102e", 1); line(-89, "#c8102e", 1);
    ctx.strokeStyle = "#1f4fa3"; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(X(0), Y(0), 15 * sx, 0, 7); ctx.stroke();
    ctx.strokeStyle = "#c8102e";
    for (const [x, y] of [[69, 22], [69, -22], [-69, 22], [-69, -22]]) { ctx.beginPath(); ctx.arc(X(x), Y(y), 15 * sx, 0, 7); ctx.stroke(); ctx.fillStyle = "#c8102e"; ctx.beginPath(); ctx.arc(X(x), Y(y), 1.4 * sx, 0, 7); ctx.fill(); }
    for (const x of [89, -89]) {
      ctx.fillStyle = "rgba(90,150,220,.25)"; ctx.beginPath(); ctx.arc(X(x), Y(0), 6 * sx, x > 0 ? Math.PI / 2 : -Math.PI / 2, x > 0 ? Math.PI * 1.5 : Math.PI / 2); ctx.fill();
      ctx.strokeStyle = "#333"; ctx.lineWidth = 2; ctx.strokeRect(x > 0 ? X(x) : X(x - 3.3), Y(3), 3.3 * sx, 6 * sy);
    }
    ctx.restore();
    return {X, Y, sx};
  }
  function fmt(t) { const p = Math.min(4, Math.floor(t / 1200) + 1), c = 1200 - (t - (p - 1) * 1200); return [p === 4 ? "OT" : ["1st", "2nd", "3rd"][p - 1], `${Math.floor(Math.max(0, c) / 60)}:${String(Math.floor(Math.max(0, c) % 60)).padStart(2, "0")}`]; }

  let live = 0;                                       // v38 (#25): only the newest 2D game draws; old loops stop
  async function mount(el, gid) {
    const me = ++live;
    el.innerHTML = '<div class="rk-wait"><div class="rk-spin"></div><p class="muted">Building the 2D game...</p></div>';
    const tr = await api("track", {id: gid});
    if (me !== live || !document.body.contains(el)) return;
    const hc = teamColours(tr.home.abbr), ac = ["#ffffff", teamColours(tr.away.abbr)[0]];   // the road team wears white
    el.innerHTML = `<div class="rk"><div class="rk-hud"><span class="rk-team" style="--c:${ac[1]}">${esc(tr.away.abbr)}</span><b id="rk-as">0</b><span id="rk-clock" class="rk-clock">1st 20:00</span><b id="rk-hs">0</b><span class="rk-team" style="--c:${hc[0]}">${esc(tr.home.abbr)}</span>
        <span id="rk-note" class="rk-note"></span></div>
      <canvas id="rk-c"></canvas>
      <div class="rk-ctl"><button id="rk-play" class="primary">Play</button><button id="rk-prev">&#9664;&#9664; Goal</button><button id="rk-next">Goal &#9654;&#9654;</button><button id="rk-shot">Next shot &#9654;</button>
        <label>Speed <select id="rk-speed">${[1, 2, 4, 8, 16, 32].map((v) => `<option value="${v}"${v === 4 ? " selected" : ""}>${v}x</option>`).join("")}</select></label>
        <input type="range" id="rk-pos" min="0" max="${tr.frames.length - 1}" value="0"><span id="rk-per" class="muted small"></span></div>
      <div class="rk-ice"><div><b>${esc(tr.away.abbr)} on the ice</b><ul id="rk-away"></ul></div><div><b>${esc(tr.home.abbr)} on the ice</b><ul id="rk-home"></ul></div></div>
      <p class="muted small">The 2D game: the match engine's events (who shot, from where, the result) played out by the 2D engine. Positions between events are the engine's, not real tracking.</p></div>`;
    const cv = $("#rk-c"), ctx = cv.getContext("2d");
    const fit = () => { cv.width = cv.clientWidth * devicePixelRatio; cv.height = cv.clientWidth * H / W * devicePixelRatio; };
    fit();
    const dt = tr.dt, n = tr.frames.length;
    const goals = tr.marks.filter((m) => m.type === "goal"), shots = tr.marks.filter((m) => m.type !== "penalty");
    let pos = 0, playing = false, last = 0, speed = 4;
    const rosterAt = (t) => { let r = tr.rosters[0][1]; for (const [rt, ids] of tr.rosters) { if (rt <= t) r = ids; else break; } return r; };
    const score = (t) => { let h = 0, a = 0; for (const g of goals) if (g.t <= t) { if (g.team === "home") h++; else a++; } return [h, a]; };
    let lastRoster = null, flash = null;
    function frame() {
      const i = Math.floor(pos), f = pos - i, A = tr.frames[i], B = tr.frames[Math.min(n - 1, i + 1)];
      const P = tr.frames[Math.max(0, i - 1)], Q = tr.frames[Math.min(n - 1, i + 2)];
      // v38 (#3): Catmull-Rom through the frames on either side, so skaters glide instead of moving in straight jerks
      const lerp = (k) => {
        if (A[k] == null) return null;
        if (B[k] == null) return A[k];
        const p0 = P[k] == null ? A[k] : P[k], p3 = Q[k] == null ? B[k] : Q[k], p1 = A[k], p2 = B[k];
        if (Math.abs(p2 - p1) > 30) return p1 + (p2 - p1) * f;      // a line change or a faceoff: no spline across the jump
        const f2 = f * f, f3 = f2 * f;
        return 0.5 * (2 * p1 + (-p0 + p2) * f + (2 * p0 - 5 * p1 + 4 * p2 - p3) * f2 + (-p0 + 3 * p1 - 3 * p2 + p3) * f3);
      };
      const {X, Y, sx} = draw(ctx, cv.width, cv.height);
      const t = pos * dt, ids = rosterAt(t), carrier = A[26];
      // skaters and goalies
      const placed = [];
      const label = (txt, cx, cy, up) => {                       // v38 (#4): at the draw, one name above and one below
        ctx.font = `${Math.max(9, 2.4 * sx)}px Tahoma, sans-serif`; ctx.textAlign = "center";
        const w = ctx.measureText(txt).width, h = Math.max(9, 2.4 * sx);
        let ly = up ? cy - 3.4 * sx : cy + 3.4 * sx + h * 0.8;
        for (let tries = 0; tries < 3; tries++) {
          const hit = placed.find((b) => Math.abs(b.x - cx) < (b.w + w) / 2 && Math.abs(b.y - ly) < h);
          if (!hit) break;
          ly = up ? hit.y - h : hit.y + h;
        }
        placed.push({x: cx, y: ly, w});
        ctx.lineWidth = 3; ctx.strokeStyle = "rgba(246,249,252,.9)"; ctx.strokeText(txt, cx, ly);
        ctx.fillStyle = "#1b2a3e"; ctx.fillText(txt, cx, ly);
      };
      // v38 (#3): the puck's tracer, blue for a pass and red for a shot, and a glowing puck
      const tt = pos * dt;
      const shotSoon = shots.some((m) => m.t >= tt - 0.4 && m.t <= tt + 1.2);
      const trail = [];
      for (let k = 0; k <= 6; k++) {
        const q = Math.max(0, pos - k * 0.5), qi = Math.floor(q), qf = q - qi, Fa = tr.frames[qi], Fb = tr.frames[Math.min(n - 1, qi + 1)];
        if (Fa[0] == null) break;
        trail.push([Fa[0] + ((Fb[0] ?? Fa[0]) - Fa[0]) * qf, Fa[1] + ((Fb[1] ?? Fa[1]) - Fa[1]) * qf, Fa[26]]);
      }
      if (trail.length > 2 && trail[0][2] == null) {
        const speedNow = Math.hypot(trail[0][0] - trail[1][0], trail[0][1] - trail[1][1]) / (0.5 * dt);
        if (speedNow > 20) {
          const col = shotSoon ? "255,40,40" : "40,110,255";
          for (let k = 0; k < trail.length - 1; k++) {
            if (trail[k + 1][2] != null && k > 0) break;
            ctx.strokeStyle = `rgba(${col},${0.85 - k * 0.13})`; ctx.lineWidth = (2.2 - k * 0.25) * sx * 0.6; ctx.lineCap = "round";
            ctx.beginPath(); ctx.moveTo(X(trail[k][0]), Y(trail[k][1])); ctx.lineTo(X(trail[k + 1][0]), Y(trail[k + 1][1])); ctx.stroke();
          }
        }
      }
      for (let j = 0; j < 12; j++) {
        const x = lerp(2 + 2 * j), y = lerp(3 + 2 * j);
        if (x == null) continue;
        const home = j < 5 || j === 10, col = home ? hc : ac, pid = ids[j], p = tr.players[pid];
        ctx.fillStyle = col[0]; ctx.strokeStyle = col[1]; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(X(x), Y(y), (j >= 10 ? 2.6 : 2.2) * sx, 0, 7); ctx.fill(); ctx.stroke();
        if (j === carrier) { ctx.strokeStyle = "#111"; ctx.lineWidth = 2; ctx.setLineDash([3, 2]); ctx.beginPath(); ctx.arc(X(x), Y(y), 4.2 * sx, 0, 7); ctx.stroke(); ctx.setLineDash([]); }   // the carrier: a dashed black ring (club trims can be gold)
        if (p) label(p[0].split(" ").pop(), X(x), Y(y), home);
      }
      const px = lerp(0), py = lerp(1);
      const glow = ctx.createRadialGradient(X(px), Y(py), 0, X(px), Y(py), 4 * sx);
      glow.addColorStop(0, "rgba(120,200,255,.75)"); glow.addColorStop(1, "rgba(120,200,255,0)");
      ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(X(px), Y(py), 4 * sx, 0, 7); ctx.fill();
      ctx.fillStyle = "#111"; ctx.beginPath(); ctx.arc(X(px), Y(py), 1.1 * sx, 0, 7); ctx.fill();
      if (flash && t - flash.t < 2.5) { ctx.fillStyle = "rgba(200,30,50,.85)"; ctx.font = `bold ${5 * sx}px Tahoma, sans-serif`; ctx.textAlign = "center"; ctx.fillText(flash.text, X(0), Y(30)); }
      const [per, clk] = fmt(t); $("#rk-clock").textContent = `${per} ${clk}`;
      const [hs, as] = score(t); $("#rk-hs").textContent = hs; $("#rk-as").textContent = as;
      $("#rk-pos").value = i;
      pbp(t);
      const key = ids.join(",");
      if (key !== lastRoster) {
        lastRoster = key;
        const li = (k) => ids.slice(k, k + 5).concat([ids[10 + (k ? 1 : 0)]]).filter((x) => x && tr.players[x]).map((x) => `<li><span class="muted">${esc(tr.players[x][1])}</span> ${esc(tr.players[x][0])}</li>`).join("");
        $("#rk-home").innerHTML = li(0); $("#rk-away").innerHTML = li(5);
      }
    }
    function tick(ts) {
      if (!document.body.contains(cv) || me !== live) return;
      if (playing) {
        const el2 = last ? Math.min(0.1, (ts - last) / 1000) : 0;     // a hidden tab or a slow frame never jumps the game
        pos = Math.min(n - 1, pos + el2 * speed / dt);
        const t = pos * dt;
        for (const m of shots) if (m.t > t - el2 * speed && m.t <= t) {
          $("#rk-note").textContent = `${m.type === "goal" ? "GOAL" : m.type === "shot" ? "Save" : m.type === "block" ? "Blocked" : "Wide"}: ${m.who || ""} (${m.team === "home" ? tr.home.abbr : tr.away.abbr})`;
          if (m.type === "goal") flash = {t: m.t, text: `GOAL ${m.team === "home" ? tr.home.abbr : tr.away.abbr}`};
        }
        if (pos >= n - 1) { playing = false; $("#rk-play").textContent = "Play"; }
      }
      last = ts;
      frame();
      requestAnimationFrame(tick);
    }
    const jump = (t) => { pos = Math.max(0, Math.min(n - 1, t / dt)); };
    // v38 (#5): play by play beside the recap and the score by period, following the replay
    const right = el.closest(".grid.g21") ? el.closest(".grid.g21").children[1] : null;
    if (right && !right.querySelector("#rk-pbp")) right.insertAdjacentHTML("beforeend", panel("Play by play", '<ul id="rk-pbp" class="rk-pbp"></ul>'));
    const word = {goal: "GOAL", shot: "Shot, saved", miss: "Shot, wide", block: "Shot, blocked", penalty: "Penalty"};
    let pbpAt = -1;
    const pbp = (t) => {
      const ul = $("#rk-pbp");
      if (!ul) return;
      const seen = tr.marks.filter((m) => m.t <= t);
      if (seen.length === pbpAt) return;
      pbpAt = seen.length;
      ul.innerHTML = seen.slice(-14).reverse().map((m) => { const [pp, cc] = fmt(m.t); const ab = m.team === "home" ? tr.home.abbr : tr.away.abbr;
        return `<li class="${m.type}" data-t="${m.t}"><span class="when">${pp} ${cc}</span><b>${esc(ab)}</b> ${esc(word[m.type] || m.type)}${m.who ? ": " + esc(m.who) : ""}</li>`; }).join("")
        || '<li class="muted">The puck is about to drop.</li>';
      ul.querySelectorAll("[data-t]").forEach((li) => (li.onclick = () => jump(+li.dataset.t - 6)));
    };
    $("#rk-play").onclick = () => { playing = !playing; $("#rk-play").textContent = playing ? "Pause" : "Play"; };
    $("#rk-speed").onchange = (e) => { speed = +e.target.value; };
    $("#rk-pos").oninput = (e) => { pos = +e.target.value; };
    $("#rk-next").onclick = () => { const g = goals.find((m) => m.t > pos * dt + 0.5); if (g) jump(g.t - 8); };
    $("#rk-prev").onclick = () => { const g = [...goals].reverse().find((m) => m.t < pos * dt - 9); jump(g ? g.t - 8 : 0); };
    $("#rk-shot").onclick = () => { const s = shots.find((m) => m.t > pos * dt + 0.5); if (s) jump(s.t - 6); };
    window.addEventListener("resize", fit);
    requestAnimationFrame(tick);
  }
  return {mount};
})();
