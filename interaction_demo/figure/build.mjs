// Builds interaction_demo/bench_figure.html: an isometric bench rig (three knobs, three LEDs, a buzzer).
// Needs the Anatomy kit: ANATOMY_KIT=/path/to/anatomy node interaction_demo/figure/build.mjs
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { homedir } from "node:os";

const KIT = process.env.ANATOMY_KIT || join(homedir(), ".claude/skills/anatomy");
const k = await import(pathToFileURL(join(KIT, "kit/iso-kit.mjs")).href);
const { kitScript } = await import(pathToFileURL(join(KIT, "scripts/inline-kit.mjs")).href);
const HERE = dirname(fileURLToPath(import.meta.url));

const WIDTH = 700, HEIGHT = 380;
const PLATE = { x: -190, y: -100, w: 380, d: 200, r: 10 };
const PLATE_H = 12, FOOT_H = 5;
// Raspberry Pi board (left), breadboard (right), buzzer (front right)
const PI = { x: -176, y: -84, w: 176, d: 112, r: 6 };
const PI_Z = 7, PI_T = 2.4;               // standoff height, board thickness
const PI_TOP = PI_Z + PI_T;
const BB = { x: 34, y: -84, w: 140, d: 76, r: 3 };
const BB_H = 7;
const LX = [62, 104, 146], LY = -52;       // LED columns on the breadboard
const BUZ = { x: 110, y: 52, r: 20, h: 13 };
const PINS = [18, 13, 19];                 // GPIO numbers wired to LED 1-3
const BAR_Y = -20, BAR_W = 30;             // duty-cycle ruler on the breadboard
const LED_BASE = BB_H + 1.2;

const P = k.fitProjection(
  [...k.boxCorners(PLATE, -PLATE_H - FOOT_H, 0), [BUZ.x, BUZ.y, 40], [PI.x, PI.y, 30]],
  WIDTH, HEIGHT, { pad: 12, azimuth: 38 },
);
const at = (p) => k.iso(p, P);
const S = (paths, style) => k.solidSvg(paths, style);
const L = (d, style) => k.lineSvg(d, style);
const D = (pts, style) => k.dotsSvg(pts, style);
const T = (cx, cy, z, text, size = 3, tone = "lo") => k.faceTextSvg(k.topMatrix([cx, cy], z, P, "x"), text, { size, tone, anchor: "middle" });
const slab = (plan, z, h, tone = "mid", opt = {}) => S(k.slabOf(plan, z, h, P, opt.steps ?? 3, opt.bevel ?? 0.4), { tone, crease: opt.crease });

function plate() {
  const out = [`<path class="iso-halo" d="${k.haloOf(PLATE, -PLATE_H - FOOT_H, PLATE_H, P)}"/>`];
  const foot = [...k.corners(PLATE, 24)].sort((a, b) => k.depthOf([a[0], a[1], 0], P) - k.depthOf([b[0], b[1], 0], P));
  for (const [x, y] of foot) {
    out.push(S(k.cylinder(x, y, 7, -PLATE_H - FOOT_H, 1.6, P, 28), { tone: "lo" }));
    out.push(S(k.cylinder(x, y, 5.4, -PLATE_H - FOOT_H + 1.6, FOOT_H - 1.6, P, 28), { tone: "mid" }));
  }
  out.push(S(k.slabOf(PLATE, -PLATE_H, PLATE_H, P, 8, 1.6), { tone: "mid" }));
  out.push(L(k.planOutline(k.insetPlan(PLATE, 5), 0, P), { tone: "lo" }));
  const screws = k.corners(PLATE, 11);
  out.push(L(screws.map(([x, y]) => k.ring(x, y, 2.2, 0, P, 16)).join(""), { tone: "lo" }));
  out.push(D(screws.map(([x, y]) => at([x, y, 0])), { size: 0.5 }));
  return out.join("");
}

function piBoard() {
  const out = [`<path class="iso-halo" d="${k.haloOf(PI, 0, PI_Z, P)}" style="filter:blur(5px)"/>`];
  // four standoffs on the corner mounting holes
  const holes = [[PI.x + 6, PI.y + 6], [PI.x + 64, PI.y + 6], [PI.x + 6, PI.y + PI.d - 6], [PI.x + 64, PI.y + PI.d - 6]];
  const hs = [...holes].sort((a, b) => k.depthOf([a[0], a[1], 0], P) - k.depthOf([b[0], b[1], 0], P));
  for (const [x, y] of hs) out.push(S(k.cylinder(x, y, 3.2, 0, PI_Z, P, 16), { tone: "lo", crease: "none" }));
  out.push(S(k.slabOf(PI, PI_Z, PI_T, P, 6, 0.5), { tone: "mid" }));
  out.push(L(k.planOutline(k.insetPlan(PI, 2.4), PI_TOP, P, 6), { tone: "faint" }));
  out.push(L(holes.map(([x, y]) => k.ring(x, y, 2, PI_TOP, P, 14)).join(""), { tone: "lo" }));
  out.push(D(holes.map(([x, y]) => at([x, y, PI_TOP])), { size: 0.4 }));
  // SoC with a heat-spreader lid, RAM, wireless shield
  out.push(slab({ x: PI.x + 48, y: PI.y + 40, w: 28, d: 28, r: 2 }, PI_TOP, 2.6, "mid"));
  out.push(slab({ x: PI.x + 51, y: PI.y + 43, w: 22, d: 22, r: 1.5 }, PI_TOP + 2.6, 1.2, "hi", { crease: "lo" }));
  out.push(slab({ x: PI.x + 86, y: PI.y + 44, w: 20, d: 14, r: 1.5 }, PI_TOP, 1.6, "lo"));
  out.push(slab({ x: PI.x + 14, y: PI.y + 36, w: 22, d: 18, r: 1.5 }, PI_TOP, 3, "mid"));
  out.push(L(k.lineOnTop([PI.x + 17, PI.y + 45], [PI.x + 33, PI.y + 45], PI_TOP + 3, P), { tone: "faint" }));
  // USB-A stack, Ethernet jack, USB-C power, micro-HDMI at the board edges
  out.push(slab({ x: PI.x + PI.w - 22, y: PI.y + 62, w: 24, d: 15, r: 1 }, PI_TOP, 13, "hi", { crease: "lo" }));
  out.push(slab({ x: PI.x + PI.w - 22, y: PI.y + 82, w: 24, d: 15, r: 1 }, PI_TOP, 13, "hi", { crease: "lo" }));
  out.push(slab({ x: PI.x + PI.w - 24, y: PI.y + 98, w: 26, d: 13, r: 1 }, PI_TOP, 11, "hi", { crease: "lo" }));
  out.push(slab({ x: PI.x + 28, y: PI.y + PI.d - 4, w: 12, d: 5, r: 1 }, PI_TOP, 3.2, "mid"));
  out.push(slab({ x: PI.x + 46, y: PI.y + PI.d - 4, w: 8, d: 5, r: 1 }, PI_TOP, 2.6, "mid"));
  out.push(slab({ x: PI.x + 58, y: PI.y + PI.d - 4, w: 8, d: 5, r: 1 }, PI_TOP, 2.6, "mid"));
  out.push(slab({ x: PI.x - 2, y: PI.y + 32, w: 12, d: 22, r: 1 }, PI_TOP - 1, 1.6, "lo"));   // microSD slot
  out.push(T(PI.x + 62, PI.y + 78, PI_TOP, "RASPBERRY PI", 4.4, "mid"));
  return out.join("");
}

// 2 x 20 GPIO header along the back (y) edge of the Pi, pins numbered like the real pinout
const HDR = { x: PI.x + 16, y: PI.y + 4, w: 106, d: 9, r: 1 };
const pinAt = (n) => [HDR.x + 3.6 + Math.floor(n / 2) * 5.2, HDR.y + 2.4 + (n % 2) * 4.2, PI_TOP + 8];
function header() {
  const out = [slab(HDR, PI_TOP, 4, "lo", { bevel: 0.3 })];
  const pins = [];
  for (let n = 0; n < 40; n++) pins.push(pinAt(n));
  out.push(D(pins.map((p) => at([p[0], p[1], PI_TOP + 4])), { size: 0.5, tone: "hi" }));
  out.push(S(k.cylinder(pins[0][0], pins[0][1], 0.1, PI_TOP + 4, 0.1, P, 4), { tone: "hi" }));
  out.push(T(HDR.x + HDR.w / 2, HDR.y - 4.5, PI_TOP, "GPIO", 3.2, "mid"));
  return out.join("");
}

function breadboard() {
  const out = [`<path class="iso-halo" d="${k.haloOf(BB, 0, BB_H, P)}" style="filter:blur(5px)"/>`];
  out.push(slab(BB, 0, BB_H, "mid", { steps: 4, bevel: 0.7 }));
  out.push(L(k.planOutline(k.insetPlan(BB, 2.4), BB_H, P, 4), { tone: "faint" }));
  const holes = [];
  for (let r = 0; r < 5; r++) for (let c = 0; c < 21; c++) {
    holes.push(at([BB.x + 12 + c * 6.2, BB.y + 7 + r * 3.8, BB_H]));
    holes.push(at([BB.x + 12 + c * 6.2, BB.y + 41 + r * 3.8, BB_H]));
  }
  out.push(D(holes, { size: 0.32, tone: "lo" }));
  out.push(L(k.lineOnTop([BB.x + 5, BB.y + 31], [BB.x + BB.w - 5, BB.y + 31], BB_H, P), { tone: "faint" }));
  out.push(L(k.lineOnTop([BB.x + 5, BB.y + 34], [BB.x + BB.w - 5, BB.y + 34], BB_H, P), { tone: "faint" }));
  LX.forEach((x) => { out.push(L(k.lineOnTop([x - 1.6, BB.y + 7], [x - 1.6, LY - 5.6], BB_H, P), { tone: 'lo' })); });
  // duty-cycle ruler under each LED column, 0 to 255
  LX.forEach((x, i) => {
    const s = { x: x - BAR_W / 2, y: BAR_Y + 4.5, w: BAR_W, d: 3, r: 0.6 };
    out.push(S(k.slabOf(s, BB_H, 0.5, P, 2), { tone: "lo", crease: "none" }));
    out.push(L(k.topTicks(s.x + 1, s.x + s.w - 1, 3, 5, s.y + 0.6, BB_H + 0.5, [1, 1.8], P).major, { tone: "mid" }));
    out.push(T(x, BAR_Y + 14, BB_H, `LED ${i + 1} · GPIO ${PINS[i]}`, 2.6, "mid"));
  });
  return out.join("");
}

const barD = (v, i) => k.lineOnTop([LX[i] - BAR_W / 2, BAR_Y], [LX[i] - BAR_W / 2 + BAR_W * (v / 255), BAR_Y], BB_H + 0.8, P);

function ledPart(i) {
  const x = LX[i], y = LY;
  const out = [];
  const glow = { x: x - 16, y: y - 16, w: 32, d: 32, r: 16 };
  out.push(`<path data-glow="${i}" class="iso-halo" d="${k.haloOf(glow, BB_H, 1, P)}" style="fill:var(--anatomy-red);opacity:0;filter:blur(8px);transform:none"/>`);
  // current-limiting resistor lying across the rows beside the LED, with colour-band ticks
  const rx = x - 16, ry = y + 12;
  out.push(S(k.cylinder(rx, ry, 2.2, BB_H + 0.8, 1, P, 16), { tone: "lo", crease: "none" }));
  out.push(slab({ x: rx - 1.4, y: ry - 5.5, w: 2.8, d: 11, r: 1.2 }, BB_H + 0.8, 2.6, "mid", { steps: 3, bevel: 0.3 }));
  out.push(L([-3, -1, 1.2, 3.2].map((o) => k.lineOnTop([rx - 1.4, ry + o], [rx + 1.4, ry + o], BB_H + 3.4, P)).join(""), { tone: "hi" }));
  out.push(D([at([rx, ry - 5.5, BB_H + 0.8]), at([rx, ry + 5.5, BB_H + 0.8])], { size: 0.45, tone: "hi" }));
  // 5 mm LED: flange, body, dome and two legs
  out.push(S(k.cylinder(x, y, 5.6, LED_BASE, 1.3, P, 28, 0.3), { tone: "mid" }));
  out.push(S(k.cylinder(x, y, 4.6, LED_BASE + 1.3, 6.5, P, 24, 0.3), { tone: "hi", lit: true }));
  out.push(S(k.cylinder(x, y, 2.9, LED_BASE + 7.8, 2.2, P, 20, 1.1), { tone: "hi", lit: true }));
  out.push(`<path data-lens="${i}" class="iso-line" data-tone="lit" d="${k.ring(x, y, 1.8, LED_BASE + 10, P, 14)}" style="opacity:.15"/>`);
  out.push(L(k.lineOnTop([x - 1.6, y + 5.6], [x - 1.6, y + 12], BB_H + 0.8, P), { tone: "mid" }));
  out.push(L(k.lineOnTop([x + 1.6, y + 5.6], [x + 1.6, y + 12], BB_H + 0.8, P), { tone: "mid" }));
  return out.join("");
}

function buzzer() {
  const { x, y, r, h } = BUZ;
  const H = { x: x - 28, y: y - 26, w: 56, d: 52, r: 6 };
  const out = [`<path class="iso-halo" d="${k.haloOf(H, 0, 2, P)}" style="filter:blur(4px)"/>`];
  out.push(slab(H, 0, 4, "mid", { steps: 6, bevel: 0.7 }));
  out.push(L(k.planOutline(k.insetPlan(H, 3), 4, P), { tone: "faint" }));
  out.push(S(k.cylinder(x, y, r, 4, h, P, 48, 0.8), { tone: "hi", lit: true }));
  out.push(L(k.ring(x, y, r - 3, 4 + h, P, 48), { tone: "lo" }));
  out.push(L(k.ring(x, y, 3.4, 4 + h, P, 20), { tone: "mid" }));
  out.push(D([at([x, y, 4 + h])], { size: 0.5, tone: "hi" }));
  out.push(T(x, y + 21.5, 4, "PIEZO BUZZER", 2.8, "mid"));
  // two pins that carry the signal and ground wires
  out.push(S(k.cylinder(x - 9, y - 26 + 0, 1.5, 4, 3, P, 12), { tone: "hi", crease: "none" }));
  return out.join("");
}

// jumper wires: GPIO header pin -> LED row on the breadboard (arched, ends on pins), plus the buzzer lead
function wires() {
  const out = [];
  const gpio = [[13, "mid"], [14, "mid"], [15, "mid"]];       // pin indices along the header, spaced apart
  const picks = [26, 30, 34];
  picks.forEach((n, i) => {
    const a = pinAt(n), b = [LX[i] - 1.6, BB.y + 7, BB_H];
    out.push(k.wireSvg(at(a), at(b), { via: [at([a[0], a[1] + 4, a[2] + 12 + i * 3]), at([b[0], b[1] - 4, 20 + i * 3])], tone: i === 1 ? "hi" : "mid", size: 1.1 }));
  });
  const g = pinAt(8), bz = [BUZ.x - 9, BUZ.y - 24.5, 7];
  out.push(k.wireSvg(at(g), at(bz), { via: [at([g[0], g[1] + 6, g[2] + 8]), at([bz[0], bz[1] - 10, 14])], tone: "hi", size: 1.1 }));
  return out.join("");
}

const waves = [0, 1, 2].map((i) => `<path data-wave="${i}" class="iso-line" data-tone="lit" d="${k.ring(BUZ.x, BUZ.y, BUZ.r + 8 + i * 8, 4 + BUZ.h + 3 + i * 3, P, 56)}" style="opacity:0;stroke-width:1"/>`).join("");

const body = [
  plate(), piBoard(), header(), breadboard(),
  ...[0, 1, 2].map((i) => `<g data-knob="${i}" tabindex="0" role="slider" aria-label="LED ${i + 1} duty value, 0 to 255" aria-valuemin="0" aria-valuemax="255" aria-valuenow="128">${ledPart(i)}<path data-pointer="${i}" class="iso-line" data-tone="lit" data-free="start" d="${barD(128, i)}" style="stroke-width:1.6"/></g>`),
  buzzer(), waves, wires(),
];

const svg = k.figureSvg({
  width: WIDTH, height: HEIGHT,
  label: "A Raspberry Pi wired to a breadboard with three LEDs on GPIO 18, 13 and 19, each with a current-limiting resistor, and to a piezo buzzer. Dragging an LED sets its 0 to 255 duty value. The simulator then says whether the buzzer still rings at those three values; a silent buzzer is a failure.",
  body,
});

const live = `
const P = ${JSON.stringify(P)};
const LX = ${JSON.stringify(LX)}, BAR_Y = ${BAR_Y}, BAR_W = ${BAR_W}, BAR_Z = ${BB_H + 0.8};
const root = document.querySelector("[data-bench-figure]");
const svg = root.querySelector("svg");
const readout = root.closest("[data-bench]").querySelector("[data-readout]");
const knobs = [0, 1, 2].map((i) => svg.querySelector('[data-knob="' + i + '"]'));
const pointers = [0, 1, 2].map((i) => knobs[i].querySelector("[data-pointer]"));
const glows = [0, 1, 2].map((i) => svg.querySelector('[data-glow="' + i + '"]'));
const lenses = [0, 1, 2].map((i) => svg.querySelector('[data-lens="' + i + '"]'));
const waves = [0, 1, 2].map((i) => svg.querySelector('[data-wave="' + i + '"]'));
const still = matchMedia("(prefers-reduced-motion: reduce)");
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const values = [128, 128, 128], shown = [128, 128, 128];
let sound = null, hum = 0, frame = 0, last = 0, clock = 0, visible = false, probeTimer = 0, probeSeq = 0;
const pointerAt = (value, i) => lineOnTop([LX[i] - BAR_W / 2, BAR_Y], [LX[i] - BAR_W / 2 + BAR_W * (value / 255), BAR_Y], BAR_Z, P);
function text() {
  const v = values.join(" / ");
  if (sound === null) return v + (probeSeq && !probeTimer ? " · running on bench" : " · probing");
  return v + (sound.ok ? " · PASS · buzzer rings, " + sound.hz + " Hz" : " · FAIL · buzzer silent");
}
function draw() {
  for (let i = 0; i < 3; i++) {
    pointers[i].setAttribute("d", pointerAt(shown[i], i));
    const b = shown[i] / 255;
    glows[i].style.opacity = String((b * 0.95).toFixed(3));
    lenses[i].style.opacity = String((0.15 + b * 0.85).toFixed(3));
  }
  for (let w = 0; w < 3; w++) {
    const phase = ((clock * 0.9 - w * 0.22) % 1 + 1) % 1;
    waves[w].style.opacity = sound && sound.ok ? String((still.matches ? 0.5 - w * 0.12 : (1 - phase) * 0.9 * hum).toFixed(3)) : "0";
  }
  const t = text();
  if (readout.textContent !== t) readout.textContent = t;
}
function tick(now) {
  const dt = last ? Math.min((now - last) / 1000, 1 / 30) : 1 / 60;
  last = now; clock += dt;
  let moving = false;
  for (let i = 0; i < 3; i++) {
    const d = values[i] - shown[i];
    shown[i] = still.matches || Math.abs(d) < 0.05 ? values[i] : shown[i] + d * (1 - Math.exp(-dt / 0.09));
    if (shown[i] !== values[i]) moving = true;
  }
  hum += ((sound && sound.ok ? 1 : 0) - hum) * (1 - Math.exp(-dt / 0.25));
  draw();
  const animating = moving || (sound && sound.ok && !still.matches) || hum > 0.01;
  frame = visible && animating ? requestAnimationFrame(tick) : 0;
}
const run = () => { if (!frame && visible) { last = 0; frame = requestAnimationFrame(tick); } };
new IntersectionObserver((e) => { visible = e[e.length - 1].isIntersecting; if (visible) run(); }, { rootMargin: "120px 0px" }).observe(root);
async function probe() {
  const seq = ++probeSeq;
  try {
    const r = await fetch("/api/probe", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ led1: values[0], led2: values[1], led3: values[2] }) });
    const v = await r.json();
    if (seq !== probeSeq) return;
    if (!r.ok) throw Error(v.error);
    sound = { ok: v.outcome === "PASS", hz: v.measurements.frequency_hz };
  } catch (e) { if (seq === probeSeq) sound = null; }
  draw(); run();
}
function set(next, notify = true, given = undefined) {
  next.forEach((v, i) => { values[i] = clamp(Math.round(v), 0, 255); knobs[i].setAttribute("aria-valuenow", String(values[i])); knobs[i].setAttribute("aria-valuetext", "LED " + (i + 1) + " " + values[i]); });
  sound = null; draw(); run();
  clearTimeout(probeTimer);
  if (given === 'wait') { probeSeq++; draw(); return; }                // a campaign step is running on the bench: no extra probe
  if (given) { probeSeq++; sound = { ok: given.outcome === 'PASS', hz: given.measurements ? given.measurements.frequency_hz : 0 }; draw(); run(); return; }
  probeTimer = setTimeout(probe, 120);
  if (notify) root.dispatchEvent(new CustomEvent("bench-change", { detail: { values: [...values] } }));
}
knobs.forEach((knob, i) => {
  let from = null;
  knob.style.cursor = "ns-resize"; knob.style.outline = "none";
  knob.addEventListener("pointerdown", (e) => { from = { x: e.clientX, y: e.clientY, v: values[i] }; knob.setPointerCapture(e.pointerId); knob.style.cursor = "ns-resize"; knob.focus({ preventScroll: true }); e.preventDefault(); });
  knob.addEventListener("pointermove", (e) => { if (!from) return; const n = [...values]; n[i] = from.v + (e.clientX - from.x) * 0.9 - (e.clientY - from.y) * 0.9; set(n); });
  const end = () => { from = null; knob.style.cursor = "ns-resize"; };
  knob.addEventListener("pointerup", end); knob.addEventListener("pointercancel", end);
  knob.addEventListener("keydown", (e) => {
    const step = e.shiftKey ? 10 : 1; let v = values[i];
    if (e.key === "ArrowUp" || e.key === "ArrowRight") v += step; else if (e.key === "ArrowDown" || e.key === "ArrowLeft") v -= step;
    else if (e.key === "PageUp") v += 25; else if (e.key === "PageDown") v -= 25; else if (e.key === "Home") v = 0; else if (e.key === "End") v = 255; else return;
    e.preventDefault(); const n = [...values]; n[i] = v; set(n);
  });
});
root.set = (v) => set(v, false);
window.benchFigure = { set: (v, given) => set(v, false, given), get: () => [...values] };
set(values, false);
`;

const fig = k.plateHtml({
  fig: "Fig 1",
  title: "Pi test bench",
  hint: "Drag an LED up or down, or focus it and use the arrow keys",
  readout: "128 / 128 / 128 · probing",
  keys: [
    { mark: "lit", label: "Duty bars, LED glow and buzzer sound: set by your input and the simulator's answer" },
    { mark: "raised", label: "Raspberry Pi, three LEDs with resistors, piezo buzzer" },
  ],
  caption: "Drag an LED up or down to set its 0–255 duty and it brightens in proportion. The simulator then says whether the buzzer still rings at those three values; a silent buzzer is a failure. Manual probes are not recorded and do not use a campaign budget.",
  body: `<div data-bench-figure>${svg}</div>`,
});

const html = `<div class="iso" data-theme="light" data-bench>${fig.replace('<div data-bench-figure>', '<div data-bench-figure>')}</div>`;
const fragment = `<style>${k.ISO_CSS}.iso[data-bench]{--anatomy-page:#f7f7f3;margin:0}.iso[data-bench] .iso-figure{margin:0}.iso-plate [data-bench-figure]{position:relative}</style>${html.replace('<div data-bench-figure>', '<div data-bench-figure>')}<script type="module">${(kitScript() + live).replace(/<\/(script)/gi, "<\\/$1")}</script>`;
writeFileSync(join(HERE, "..", "bench_figure.html"), fragment);
// Standalone preview for local checking (opens without the server; the probe then shows "probing").
writeFileSync(join(HERE, "preview.html"), `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bench rig</title></head><body style="margin:0;background:#f7f7f3"><main style="max-width:900px;margin:24px auto;padding:0 16px">${fragment}</main></body></html>`);
console.log("wrote bench_figure.html", fragment.length, "bytes");
