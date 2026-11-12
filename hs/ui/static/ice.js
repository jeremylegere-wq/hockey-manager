"use strict";
// v59: the 2D game, rebuilt (hs/sim/ice2d.py tracking, version 2; docs/RINK2D.md). The whole rink with benches and
// penalty boxes, every player as a jersey token that faces the way he skates and carries a stick, the puck with its
// trail, a broadcast scoreboard with strength and shots, banners for goals and penalties, and two cameras (the whole
// rink, or following the play). Frames come five a second and are glided to the screen's rate. Falls back to the old
// viewer (rink.js) if the tracking cannot be built.
const Ice = (() => {
  const VIEW_W = 208, VIEW_H = 99;                    // feet shown: the rink (200 x 85) with the benches and boxes
  const ST = {skate: 0, glide: 1, pass: 2, shoot: 3, check: 4, block: 5, celeb: 6, gset: 7, gsave: 8, gcover: 9, draw: 10, down: 11, box: 12};
  let live = 0;

  const lum = (hex) => { const n = parseInt(hex.slice(1), 16); return (0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255; };
  const shade = (hex, k) => { const n = parseInt(hex.slice(1), 16), f = (v) => Math.max(0, Math.min(255, Math.round(v * k))); return `rgb(${f(n >> 16)},${f((n >> 8) & 255)},${f(n & 255)})`; };
  const hex6 = (c, fb) => (/^#[0-9a-f]{6}$/i.test(c || "") ? c : /^#[0-9a-f]{3}$/i.test(c || "") ? "#" + c.slice(1).split("").map((x) => x + x).join("") : fb);

  function kit(tr) {
    // the home side wears its colour, the road side white with its colour as trim
    const hc = (typeof teamColours === "function" ? teamColours(tr.home.abbr) : ["#2f6fd6", "#ffffff"]);
    const ac = (typeof teamColours === "function" ? teamColours(tr.away.abbr) : ["#c0392b", "#ffffff"]);
    const h = hex6(tr.home.color && tr.home.color !== "#2f6fd6" ? tr.home.color : hc[0], "#2f6fd6");
    let a = hex6(tr.away.color && tr.away.color !== "#c0392b" ? tr.away.color : ac[0], "#c0392b");
    return [{body: h, trim: lum(h) > 0.6 ? "#1b2433" : "#ffffff", num: lum(h) > 0.6 ? "#1b2433" : "#ffffff", bar: h},
            {body: "#f7f8fa", trim: a, num: lum(a) > 0.75 ? "#1b2433" : a, bar: a}];
  }

  // ------------------------------------------------------------------ the rink
  function drawRink(ctx, S, tr, K) {
    const X = (x) => x * S, Y = (y) => -y * S;
    // the building around the ice
    ctx.fillStyle = "#1c2531"; ctx.fillRect(-VIEW_W / 2 * S, -VIEW_H / 2 * S, VIEW_W * S, VIEW_H * S);
    // benches (top) and penalty boxes (bottom)
    const strip = (x0, x1, y0, y1, col, label) => {
      ctx.fillStyle = col; ctx.fillRect(X(x0), Y(y0), (x1 - x0) * S, (y0 - y1) * S);
      ctx.fillStyle = "rgba(255,255,255,.55)"; ctx.font = `600 ${Math.max(8, 1.9 * S)}px system-ui, sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(label, X((x0 + x1) / 2), Y((y0 + y1) / 2));
    };
    strip(-35, -7, 48.2, 43.2, shade(K[0].bar, 0.55), tr.home.abbr + " BENCH");
    strip(7, 35, 48.2, 43.2, shade(K[1].bar, 0.55), tr.away.abbr + " BENCH");
    strip(-14.5, -2, -43.2, -48.2, "#2a3442", "");
    strip(2, 14.5, -43.2, -48.2, "#2a3442", "");
    ctx.fillStyle = "rgba(255,255,255,.5)"; ctx.font = `600 ${Math.max(7, 1.5 * S)}px system-ui, sans-serif`;
    ctx.fillText("PENALTY", X(-21), Y(-45.7)); ctx.fillText("PENALTY", X(21), Y(-45.7));
    // the ice
    const path = () => { const r = 28 * S, x0 = X(-100), x1 = X(100), y0 = Y(42.5), y1 = Y(-42.5);
      ctx.beginPath(); ctx.moveTo(x0 + r, y0); ctx.lineTo(x1 - r, y0); ctx.arcTo(x1, y0, x1, y0 + r, r); ctx.lineTo(x1, y1 - r); ctx.arcTo(x1, y1, x1 - r, y1, r);
      ctx.lineTo(x0 + r, y1); ctx.arcTo(x0, y1, x0, y1 - r, r); ctx.lineTo(x0, y0 + r); ctx.arcTo(x0, y0, x0 + r, y0, r); ctx.closePath(); };
    path();
    const g = ctx.createLinearGradient(0, Y(42.5), 0, Y(-42.5)); g.addColorStop(0, "#f4f8fc"); g.addColorStop(0.5, "#fbfdff"); g.addColorStop(1, "#eef4fa");
    ctx.fillStyle = g; ctx.fill();
    ctx.save(); path(); ctx.clip();
    const red = "#c8102e", blue = "#1d4f9e";
    const vline = (x, c, w) => { ctx.strokeStyle = c; ctx.lineWidth = w; ctx.beginPath(); ctx.moveTo(X(x), Y(42.5)); ctx.lineTo(X(x), Y(-42.5)); ctx.stroke(); };
    // the club's letters at centre ice, under the lines
    ctx.fillStyle = "rgba(29,79,158,.07)"; ctx.font = `900 ${17 * S}px system-ui, sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(tr.home.abbr, 0, 0.6 * S);
    vline(-25, blue, 1.0 * S); vline(25, blue, 1.0 * S);
    ctx.setLineDash([2.2 * S, 1.4 * S]); vline(0, red, 1.0 * S); ctx.setLineDash([]);
    vline(-89, red, 0.3 * S); vline(89, red, 0.3 * S);
    ctx.lineWidth = 0.3 * S; ctx.strokeStyle = blue; ctx.beginPath(); ctx.arc(0, 0, 15 * S, 0, 7); ctx.stroke();
    ctx.fillStyle = blue; ctx.beginPath(); ctx.arc(0, 0, 0.7 * S, 0, 7); ctx.fill();
    ctx.strokeStyle = red; ctx.fillStyle = red;
    for (const [x, y] of [[69, 22], [69, -22], [-69, 22], [-69, -22]]) {
      ctx.beginPath(); ctx.arc(X(x), Y(y), 15 * S, 0, 7); ctx.stroke();
      ctx.beginPath(); ctx.arc(X(x), Y(y), 1.0 * S, 0, 7); ctx.fill();
      for (const sx of [-1, 1]) for (const sy of [-1, 1]) {            // hash marks beside the circle
        ctx.beginPath(); ctx.moveTo(X(x + sx * 2.9), Y(y + sy * 15)); ctx.lineTo(X(x + sx * 2.9), Y(y + sy * 17.5)); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(X(x + sx * 2), Y(y + sy * 0.9)); ctx.lineTo(X(x + sx * 6), Y(y + sy * 0.9)); ctx.moveTo(X(x + sx * 2), Y(y + sy * 0.9)); ctx.lineTo(X(x + sx * 2), Y(y + sy * 3.8)); ctx.stroke();
      }
    }
    for (const [x, y] of [[20, 22], [20, -22], [-20, 22], [-20, -22]]) { ctx.beginPath(); ctx.arc(X(x), Y(y), 1.0 * S, 0, 7); ctx.fill(); }
    for (const sx of [-1, 1]) {
      // the crease, the trapezoid and the net
      ctx.fillStyle = "rgba(70,150,230,.30)"; ctx.strokeStyle = red; ctx.lineWidth = 0.25 * S;
      ctx.beginPath(); ctx.arc(X(sx * 89), 0, 6 * S, sx > 0 ? Math.PI / 2 : -Math.PI / 2, sx > 0 ? Math.PI * 1.5 : Math.PI / 2); ctx.closePath(); ctx.fill(); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(X(sx * 89), Y(11)); ctx.lineTo(X(sx * 100), Y(14)); ctx.moveTo(X(sx * 89), Y(-11)); ctx.lineTo(X(sx * 100), Y(-14)); ctx.stroke();
      const nx = sx > 0 ? X(89) : X(-92.4), nw = 3.4 * S;
      ctx.fillStyle = "#ffffff"; ctx.fillRect(nx, Y(3), nw, 6 * S);
      ctx.strokeStyle = "rgba(60,70,85,.35)"; ctx.lineWidth = 1;
      for (let i = 1; i < 6; i++) { ctx.beginPath(); ctx.moveTo(nx, Y(3) + i * S); ctx.lineTo(nx + nw, Y(3) + i * S); ctx.stroke(); }
      for (let i = 1; i < 4; i++) { ctx.beginPath(); ctx.moveTo(nx + i * nw / 4, Y(3)); ctx.lineTo(nx + i * nw / 4, Y(-3)); ctx.stroke(); }
      ctx.strokeStyle = "#c8102e"; ctx.lineWidth = Math.max(1.5, 0.35 * S); ctx.strokeRect(nx, Y(3), nw, 6 * S);
    }
    ctx.restore();
    // the boards: a dark cap with the yellow kick plate inside it
    path(); ctx.strokeStyle = "#e9c94a"; ctx.lineWidth = 0.9 * S; ctx.stroke();
    path(); ctx.strokeStyle = "#f5f7fa"; ctx.lineWidth = 0.45 * S; ctx.stroke();
    ctx.save(); ctx.translate(0, 0); path(); ctx.strokeStyle = "#39465a"; ctx.lineWidth = 0.9 * S; ctx.globalCompositeOperation = "destination-over"; ctx.lineWidth = 2.2 * S; ctx.stroke(); ctx.restore();
  }

  // ------------------------------------------------------------------ a player
  function drawPlayer(ctx, S, e, P, K, o) {
    const k = K[P.side], goalie = P.pos === "G";
    const x = e.x * S, y = -e.y * S, a = -e.f;                       // screen y runs down
    const R = (goalie ? 2.55 : 2.25) * S * o.size;
    const st = e.s;
    ctx.save(); ctx.translate(x, y);
    // shadow
    ctx.fillStyle = "rgba(20,30,45,.20)"; ctx.beginPath(); ctx.ellipse(R * 0.18, R * 0.26, R * 1.02, R * 0.95, 0, 0, 7); ctx.fill();
    ctx.rotate(a);
    const hand = P.hand === "L" ? -1 : 1;                           // which side of the body the blade is on
    if (st !== ST.box && (o.stick || goalie)) {
      // the stick: one straight shaft from the hands to a short blade on the forehand. Drawn for the puck carrier,
      // for a pass, a shot or a check, and for everyone when the camera is close; never as two feelers.
      let reach = 1.55, sweep = 0.42 * hand;
      if (st === ST.shoot) { reach = 1.85; sweep = 0.12 * hand; }
      if (st === ST.pass) { reach = 1.75; sweep = 0.22 * hand; }
      if (st === ST.check) { reach = 1.9; sweep = 0; }
      if (goalie) { reach = 1.3; sweep = 0.8 * hand; }
      const bx = Math.cos(sweep) * R * reach, by = Math.sin(sweep) * R * reach;
      ctx.lineCap = "butt";
      ctx.strokeStyle = "rgba(60,48,36,.9)"; ctx.lineWidth = Math.max(1.6, R * 0.16);
      ctx.beginPath(); ctx.moveTo(R * 0.3, by * 0.3); ctx.lineTo(bx, by); ctx.stroke();
      ctx.strokeStyle = "#1c1f25"; ctx.lineWidth = Math.max(2.2, R * (goalie ? 0.3 : 0.22));
      ctx.beginPath(); ctx.moveTo(bx - R * 0.05, by); ctx.lineTo(bx + R * 0.3, by); ctx.stroke();
    }
    // the body: wider across the shoulders than front to back, so the facing reads
    const rx = R * (goalie ? (st === ST.gsave ? 0.92 : 0.86) : 0.82), ry = R * (goalie ? (st === ST.gsave ? 1.5 : 1.12) : 1.0);
    if (goalie) {                                                    // pads either side
      ctx.fillStyle = "#e6e9ee"; ctx.strokeStyle = k.trim; ctx.lineWidth = Math.max(1, R * 0.08);
      for (const sy of [-1, 1]) { ctx.beginPath(); ctx.ellipse(R * 0.2, sy * ry * 0.72, R * 0.62, R * 0.36, 0, 0, 7); ctx.fill(); ctx.stroke(); }
    }
    ctx.beginPath(); ctx.ellipse(0, 0, rx, ry, 0, 0, 7);
    ctx.fillStyle = st === ST.down ? shade(k.body === "#f7f8fa" ? "#d9dde3" : k.body, 0.8) : k.body; ctx.fill();
    ctx.lineWidth = Math.max(1.6, R * 0.17); ctx.strokeStyle = k.trim; ctx.stroke();
    ctx.lineWidth = Math.max(0.8, R * 0.05); ctx.strokeStyle = "rgba(20,30,45,.55)"; ctx.beginPath(); ctx.ellipse(0, 0, rx + R * 0.09, ry + R * 0.09, 0, 0, 7); ctx.stroke();
    // the front of the helmet: a notch that points where he faces
    ctx.fillStyle = k.trim; ctx.beginPath(); ctx.moveTo(rx + R * 0.3, 0); ctx.lineTo(rx - R * 0.16, -R * 0.3); ctx.lineTo(rx - R * 0.16, R * 0.3); ctx.closePath(); ctx.fill();
    ctx.rotate(-a);
    // the number, always upright
    if (R > 6) {
      ctx.fillStyle = k.num; ctx.font = `800 ${Math.round(R * (String(P.num ?? "").length > 1 ? 0.92 : 1.05))}px system-ui, sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(P.num != null ? P.num : (goalie ? "G" : P.pos[0]), 0, R * 0.06);
    }
    if (st === ST.celeb) { ctx.strokeStyle = "rgba(255,196,0,.9)"; ctx.lineWidth = Math.max(1.5, R * 0.12); ctx.beginPath(); ctx.arc(0, 0, R * 1.45, 0, 7); ctx.stroke(); }
    if (o.carrier) { ctx.strokeStyle = "rgba(255,255,255,.95)"; ctx.lineWidth = Math.max(1.5, R * 0.1); ctx.beginPath(); ctx.arc(0, 0, R * 1.32, 0, 7); ctx.stroke();
      ctx.strokeStyle = "rgba(20,30,45,.5)"; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(0, 0, R * 1.4, 0, 7); ctx.stroke(); }
    if (o.name) {
      const txt = P.name.replace(/^.\. /, ""), fs = Math.max(10, R * 0.72);
      ctx.font = `600 ${fs}px system-ui, sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "top";
      ctx.lineWidth = 3; ctx.strokeStyle = "rgba(250,252,255,.92)"; ctx.strokeText(txt, 0, R * 1.42);
      ctx.fillStyle = "#1b2433"; ctx.fillText(txt, 0, R * 1.42);
    }
    ctx.restore();
  }

  // ------------------------------------------------------------------ frames
  function ents(f) { const m = new Map(); for (let i = 6; i < f.length; i += 5) m.set(f[i], {x: f[i + 1] / 10, y: f[i + 2] / 10, f: f[i + 3] * Math.PI / 36, s: f[i + 4]}); return m; }
  const angLerp = (a, b, t) => { let d = (b - a + Math.PI) % (2 * Math.PI) - Math.PI; if (d < -Math.PI) d += 2 * Math.PI; return a + d * t; };
  const fmtClock = (tr, t10) => {
    const t = t10 / 10; let per = 1, base = 0;
    for (const [p, len] of tr.periods) { if (t <= base + len + 1e-6 || p === tr.periods[tr.periods.length - 1][0]) { per = p; const left = Math.max(0, base + len - t);
      return [per, `${Math.floor(left / 60)}:${String(Math.floor(left % 60)).padStart(2, "0")}`]; } base = (p) * 1200; }
    return [per, "0:00"];
  };
  const perName = (p) => p === 5 ? "SO" : p === 4 ? "OT" : p > 5 ? `${p - 3}OT` : ["1st", "2nd", "3rd"][p - 1];

  async function mount(el, gid) {
    const me = ++live;
    el.innerHTML = '<div class="rk-wait"><div class="rk-spin"></div><p class="muted">Building the 2D game...</p></div>';
    const tr = await api("track2", {id: gid});
    if (me !== live || !document.body.contains(el)) return;
    const K = kit(tr), P = tr.players, F = tr.frames, n = F.length, dt = tr.dt;
    const nm = (i) => P.find((p) => p.id === i) || {name: "?", num: ""};
    el.innerHTML = `<div class="ice">
      <div class="ice-board">
        <div class="ice-side"><span class="ice-abbr" style="background:${K[1].bar}">${esc(tr.away.abbr)}</span><b id="ice-as">0</b><span class="ice-sog" id="ice-asog">0 SOG</span></div>
        <div class="ice-mid"><span id="ice-per">1st</span><span id="ice-clock" class="ice-clock">20:00</span><span id="ice-str" class="ice-str"></span></div>
        <div class="ice-side r"><span class="ice-sog" id="ice-hsog">0 SOG</span><b id="ice-hs">0</b><span class="ice-abbr" style="background:${K[0].bar}">${esc(tr.home.abbr)}</span></div>
      </div>
      <div class="ice-stage"><canvas id="ice-c"></canvas><div id="ice-banner" class="ice-banner"></div><div id="ice-toast" class="ice-toast"></div></div>
      <div class="ice-ctl">
        <button id="ice-play" class="primary">Play</button>
        <button id="ice-prev" title="Previous goal">&#9664;&#9664; Goal</button><button id="ice-next" title="Next goal">Goal &#9654;&#9654;</button>
        <button id="ice-shot" title="Next shot">Shot &#9654;</button>
        <label>Speed <select id="ice-speed">${[0.5, 1, 2, 4, 8, 16].map((v) => `<option value="${v}"${v === 2 ? " selected" : ""}>${v}x</option>`).join("")}</select></label>
        <label>Camera <select id="ice-cam"><option value="rink">Whole rink</option><option value="follow">Follow the play</option></select></label>
        <label><input type="checkbox" id="ice-names" checked> Names</label>
        <label><input type="checkbox" id="ice-hl"> Goals only</label>
        <button id="ice-full" title="Fill the window (Esc to leave)">Full window</button>
        <input type="range" id="ice-pos" min="0" max="${n - 1}" value="0">
      </div>
      <div class="ice-under"><div><b>${esc(tr.away.abbr)}</b><ul id="ice-away"></ul></div><div class="ice-log"><b>Play by play</b><ol id="ice-log"></ol></div><div><b>${esc(tr.home.abbr)}</b><ul id="ice-home"></ul></div></div>
      <p class="muted small">The match engine decides the game (who shot, when, the result); the 2D engine plays it out. Movement between events is the 2D engine's, not real tracking.</p></div>`;
    const cv = $("#ice-c"), ctx = cv.getContext("2d");
    const fit = () => {
      const stage = cv.parentElement, r = window.devicePixelRatio || 1;
      let w = stage.clientWidth;
      if (el.querySelector(".ice.theatre")) w = Math.min(w, (window.innerHeight - 150) * VIEW_W / VIEW_H);      // keep the controls on screen
      cv.style.width = w + "px"; cv.width = Math.round(w * r); cv.height = Math.round(w * VIEW_H / VIEW_W * r);
    };
    fit();
    const goals = tr.marks.filter((m) => m.type === "goal"), rel = tr.marks.filter((m) => m.type === "release");
    let pos = 0, playing = false, last = 0, speed = 2, cam = {x: 0, y: 0, z: 1}, lastLog = -1, lastOn = "", bannerUntil = -1, toastUntil = -1;
    const trail = [];
    const score = (f) => { let h = 0, a = 0, hs = 0, as = 0; for (const m of tr.marks) { if (m.f > f) break; if (m.type === "goal") { if (m.side === 0) h++; else a++; }
      if (m.type === "goal" || m.type === "save") { if ((m.type === "goal" ? m.side : 1 - m.side) === 0) hs++; else as++; } } return [h, a, hs, as]; };
    const text = (m) => {
      const who = m.pid != null ? nm(m.pid) : null, ab = m.side === 0 ? tr.home.abbr : m.side === 1 ? tr.away.abbr : "";
      if (m.type === "goal") return `<b>GOAL ${esc(ab)}</b> ${esc(who.name)}${m.assists && m.assists.length ? " (" + m.assists.map((a) => esc(nm(a).name)).join(", ") + ")" : " (unassisted)"}${m.en ? " into the empty net" : ""}`;
      if (m.type === "save") return `Save ${esc(who ? who.name : "")} on ${esc(nm(m.by).name)}`;
      if (m.type === "miss") return `${esc(who.name)} misses the net`;
      if (m.type === "block") return `${esc(who ? who.name : "A defender")} blocks ${esc(nm(m.by).name)}'s shot`;
      if (m.type === "penalty") return `<b>Penalty ${esc(ab)}</b> ${esc(who.name)}, ${esc(m.detail || "minor")}`;
      if (m.type === "period") return `<i>${m.n === 5 ? "Shootout" : m.n === 4 ? "Overtime" : perName(m.n) + " period"}</i>`;
      if (m.type === "so_goal") return `<b>Shootout: ${esc(who.name)} scores</b> (${esc(ab)})`;
      if (m.type === "so_miss") return `Shootout: ${esc(who.name)} is stopped (${esc(ab)})`;
      if (m.type === "goalie") return `${esc(ab)} change goalies: ${esc(who.name)} comes in`;
      return null;
    };
    const logMarks = tr.marks.filter((m) => text(m));

    function sample(p) {
      const i = Math.min(n - 1, Math.floor(p)), t = p - i, A = F[i], B = F[Math.min(n - 1, i + 1)];
      const cut = (B[1] & 2) !== 0, ea = ents(A), eb = cut ? ea : ents(B);
      const out = [];
      for (const [k, a] of ea) {
        const b = eb.get(k);
        if (!b) { out.push({k, ...a}); continue; }
        out.push({k, x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t, f: angLerp(a.f, b.f, t), s: a.s});
      }
      const mode = Math.floor(A[4] / 10), h = A[4] % 10;
      let px = A[2] / 10, py = A[3] / 10;
      if (!cut) { px += (B[2] / 10 - px) * t; py += (B[3] / 10 - py) * t; }
      const car = A[5];
      if (mode === 0 && car >= 0) {                                    // on a stick: put it on the blade, with a little stickhandling
        const c = out.find((e) => e.k === car);
        if (c) { const hand = P[car].hand === "L" ? -1 : 1, w = Math.sin(p * 1.9 + car) * 0.45;
          px = c.x + Math.cos(c.f) * 3.0 - Math.sin(c.f) * (1.0 * hand + w); py = c.y + Math.sin(c.f) * 3.0 + Math.cos(c.f) * (1.0 * hand + w); }
      }
      return {A, out, px, py, mode, h, car, i};
    }

    function frame() {
      const s = sample(pos), A = s.A, W = cv.width, H = cv.height;
      const follow = $("#ice-cam").value === "follow";
      const tz = follow ? 1.9 : 1, tx = follow ? Math.max(-48, Math.min(48, s.px)) : 0, ty = follow ? Math.max(-22, Math.min(22, s.py * 0.8)) : 0;
      const jump = (A[1] & 2) !== 0 || Math.abs(tx - cam.x) > 90;
      cam.z += (tz - cam.z) * (jump ? 1 : 0.12); cam.x += (tx - cam.x) * (jump ? 1 : 0.08); cam.y += (ty - cam.y) * (jump ? 1 : 0.08);
      const S = W / VIEW_W * cam.z;
      ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, W, H);
      ctx.translate(W / 2 - cam.x * S, H / 2 + cam.y * S);
      drawRink(ctx, S, tr, K);
      // the goal lamp
      const gm = goals.filter((m) => m.f <= s.i && s.i - m.f < 18)[0];
      if (gm) { const d = (gm.side === 0 ? 1 : -1) * (((gm.per === 2) ? -1 : 1)), gx = d * 96 * S; const gr = ctx.createRadialGradient(gx, 0, 0, gx, 0, 16 * S);
        gr.addColorStop(0, "rgba(255,40,40,.75)"); gr.addColorStop(1, "rgba(255,40,40,0)"); ctx.fillStyle = gr; ctx.beginPath(); ctx.arc(gx, 0, 16 * S, 0, 7); ctx.fill(); }
      const names = $("#ice-names").checked, size = cam.z > 1.4 ? 0.9 : 1.22;
      // players: goalies and the box first, the carrier last (on top)
      const order = s.out.slice().sort((a, b) => (a.k === s.car) - (b.k === s.car) || a.y - b.y);
      for (const e of order) drawPlayer(ctx, S, e, P[e.k], K, {size, carrier: e.k === s.car && s.mode === 0,
        stick: cam.z > 1.4 || e.k === s.car || e.s === ST.pass || e.s === ST.shoot || e.s === ST.check,
        name: names && e.s !== ST.box && (cam.z > 1.4 || e.k === s.car || P[e.k].pos === "G")});
      // the puck and its trail
      if (playing) { trail.push([s.px, s.py, s.mode]); if (trail.length > 9) trail.shift(); } else trail.length = 0;
      if (s.mode === 1 || s.mode === 2 || s.mode === 3) {
        for (let i = 1; i < trail.length; i++) { ctx.strokeStyle = `rgba(30,35,45,${0.05 * i})`; ctx.lineWidth = Math.max(1.5, 0.5 * S); ctx.lineCap = "round";
          ctx.beginPath(); ctx.moveTo(trail[i - 1][0] * S, -trail[i - 1][1] * S); ctx.lineTo(trail[i][0] * S, -trail[i][1] * S); ctx.stroke(); }
      }
      const pr = Math.max(2.6, 0.62 * S) * (1 + 0.25 * s.h);
      ctx.fillStyle = "rgba(20,30,45,.25)"; ctx.beginPath(); ctx.arc(s.px * S + s.h * 0.5 * S, -s.py * S + s.h * 0.7 * S, pr, 0, 7); ctx.fill();
      ctx.fillStyle = "#11151c"; ctx.beginPath(); ctx.arc(s.px * S, -s.py * S, pr, 0, 7); ctx.fill();
      ctx.strokeStyle = "rgba(255,255,255,.7)"; ctx.lineWidth = 1; ctx.stroke();
      // the scoreboard
      const [per, clock] = fmtClock(tr, A[0]);
      const sc = score(s.i);
      $("#ice-hs").textContent = sc[0]; $("#ice-as").textContent = sc[1]; $("#ice-hsog").textContent = sc[2] + " SOG"; $("#ice-asog").textContent = sc[3] + " SOG";
      const so = tr.marks.some((m) => m.type === "period" && m.n === 5 && m.f <= s.i);
      $("#ice-per").textContent = so ? "SO" : perName(per); $("#ice-clock").textContent = so ? "" : clock;
      let hn = 0, an = 0, hg = false, ag = false;
      for (const e of s.out) { const p = P[e.k]; if (e.s === ST.box) continue; if (p.pos === "G") { if (p.side === 0) hg = true; else ag = true; } else if (p.side === 0) hn++; else an++; }
      let str = "";
      if (!so) { if (!hg && hn > 5) str = `${tr.home.abbr} empty net`; else if (!ag && an > 5) str = `${tr.away.abbr} empty net`;
        else if (hn !== an && Math.max(hn, an) <= 5 && Math.min(hn, an) >= 3) str = `${hn > an ? tr.home.abbr : tr.away.abbr} power play ${Math.max(hn, an)} on ${Math.min(hn, an)}`;
        else if (hn === an && hn < 5 && hn >= 3) str = `${hn} on ${hn}`; }
      if (A[1] & 12) str = (str ? str + " · " : "") + "delayed penalty";
      const se = $("#ice-str"); se.textContent = str; se.style.visibility = str ? "visible" : "hidden";
      // banners and the log
      let li = -1; for (let i = 0; i < logMarks.length; i++) { if (logMarks[i].f <= s.i) li = i; else break; }
      if (li !== lastLog) {
        lastLog = li;
        $("#ice-log").innerHTML = logMarks.slice(Math.max(0, li - 6), li + 1).reverse().map((m) => { const [pp, cc] = fmtClock(tr, m.t * 10); return `<li><span class="muted">${m.type.startsWith("so_") || m.n === 5 ? "SO" : perName(m.per) + " " + cc}</span> ${text(m)}</li>`; }).join("");
        const m = li >= 0 ? logMarks[li] : null;
        if (m && s.i - m.f < 8 && (m.type === "goal" || m.type === "penalty" || m.type === "so_goal")) { const b = $("#ice-banner"); b.innerHTML = text(m); b.className = "ice-banner on " + (m.type === "penalty" ? "pen" : "goal"); bannerUntil = m.f + (m.type === "goal" ? 34 : 22); }
        else if (m && s.i - m.f < 6 && (m.type === "save" || m.type === "block" || m.type === "miss" || m.type === "so_miss")) { const b = $("#ice-toast"); b.textContent = m.type === "save" || m.type === "so_miss" ? "SAVE" : m.type === "block" ? "BLOCKED" : "WIDE"; b.className = "ice-toast on"; toastUntil = m.f + 7; }
      }
      if (bannerUntil >= 0 && (s.i > bannerUntil || s.i < bannerUntil - 40)) { $("#ice-banner").className = "ice-banner"; bannerUntil = -1; }
      if (toastUntil >= 0 && (s.i > toastUntil || s.i < toastUntil - 10)) { $("#ice-toast").className = "ice-toast"; toastUntil = -1; }
      const key = s.out.filter((e) => e.s !== ST.box).map((e) => e.k).sort().join(",");
      if (key !== lastOn) {
        lastOn = key;
        const li2 = (side) => s.out.filter((e) => P[e.k].side === side && e.s !== ST.box).sort((a, b) => "CLRDG".indexOf(P[a.k].pos[0]) - "CLRDG".indexOf(P[b.k].pos[0]))
          .map((e) => `<li><span class="ice-n" style="background:${K[side].body};color:${K[side].num};border-color:${K[side].trim}">${P[e.k].num ?? ""}</span> <a href="#player/${P[e.k].id}">${esc(P[e.k].name)}</a> <span class="muted">${P[e.k].pos}</span></li>`).join("");
        $("#ice-home").innerHTML = li2(0); $("#ice-away").innerHTML = li2(1);
      }
      $("#ice-pos").value = Math.floor(pos);
    }
    function loop(ts) {
      if (me !== live || !document.body.contains(cv)) return;
      if (playing) {
        const step = Math.min(0.1, (ts - last) / 1000) * speed / dt;
        pos += step;
        if ($("#ice-hl").checked) {                                   // goals only: jump to twelve seconds before the next one
          const i = Math.floor(pos), near = goals.find((g) => g.f >= i - 2 && g.f + 30 >= i);
          const inWin = goals.some((g) => i >= g.f - 60 && i <= g.f + 30);
          if (!inWin) { const nx = goals.find((g) => g.f - 60 > i); if (nx) pos = nx.f - 60; else { pos = n - 1; } }
        }
        if (pos >= n - 1) { pos = n - 1; playing = false; $("#ice-play").textContent = "Play"; }
      }
      last = ts;
      frame();
      requestAnimationFrame(loop);
    }
    $("#ice-play").onclick = () => { if (pos >= n - 1) pos = 0; playing = !playing; $("#ice-play").textContent = playing ? "Pause" : "Play"; };
    $("#ice-speed").onchange = (e) => { speed = +e.target.value; };
    $("#ice-pos").oninput = (e) => { pos = +e.target.value; lastLog = -2; };
    const jumpTo = (f) => { pos = Math.max(0, f); lastLog = -2; };
    $("#ice-next").onclick = () => { const g = goals.find((m) => m.f - 50 > pos + 1); if (g) jumpTo(g.f - 50); };
    $("#ice-prev").onclick = () => { const g = goals.filter((m) => m.f - 50 < pos - 10).pop(); jumpTo(g ? g.f - 50 : 0); };
    $("#ice-shot").onclick = () => { const g = rel.find((m) => m.f - 25 > pos + 1); if (g) jumpTo(g.f - 25); };
    window.addEventListener("resize", () => { if (document.body.contains(cv)) fit(); });
    const root = el.querySelector(".ice");
    const theatre = (on) => { root.classList.toggle("theatre", on); $("#ice-full").textContent = on ? "Leave full window" : "Full window"; fit(); };
    $("#ice-full").onclick = () => theatre(!root.classList.contains("theatre"));
    const keys = (e) => {
      if (!document.body.contains(cv)) { document.removeEventListener("keydown", keys, true); return; }
      if (!root.classList.contains("theatre") || /INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
      if (e.key === "Escape") theatre(false);
      else if (e.key === " ") $("#ice-play").click();
      else if (e.key === "ArrowRight") jumpTo(Math.min(n - 1, pos + 5 / dt));
      else if (e.key === "ArrowLeft") jumpTo(pos - 5 / dt);
      else return;
      e.preventDefault(); e.stopPropagation();
    };
    document.addEventListener("keydown", keys, true);
    el.__ice = {seek: jumpTo, play: () => { playing = true; $("#ice-play").textContent = "Pause"; }, frames: n, goals: goals.map((g) => g.f)};
    requestAnimationFrame(loop);
  }
  return {mount};
})();
