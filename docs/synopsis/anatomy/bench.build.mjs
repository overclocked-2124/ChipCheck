// Fig 1: the ChipCheck timing bench. A laptop runs the PC side, a micro-USB cable carries the JSONL protocol,
// an ESP32-WROOM-32 DevKit (30-pin) sits on a breadboard with an LDR on GPIO34 and a trimmer on GPIO35.
// Everything the figure shows (bars, readout) comes from the same timing model the simulator uses (PRD Part II 43).
//   node bench.build.mjs [--light]
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const SK = "/home/snehal-reddy/.claude/skills/anatomy";
const k = await import(`${SK}/kit/iso-kit.mjs`);
const G = await import(`${SK}/kit/lathe.mjs`);
const T = await import(`${SK}/kit/tube.mjs`);
const { kitScript } = await import(`${SK}/scripts/inline-kit.mjs`);

const HERE = dirname(fileURLToPath(import.meta.url));
const theme = process.argv.includes("--light") ? "light" : "dark";
const CLOSE = process.argv.includes("--close");
const WIDTH = CLOSE ? 900 : 980, HEIGHT = CLOSE ? 600 : 470;

// ------------------------------------------------------------------ world (1 unit = 0.4 mm of the real board)
const MAT = { x: -268, y: -92, w: 380, d: 184, r: 9 };
const MAT_H = 10, FOOT_H = 5;
const BB = { x: -95, y: -67, w: 190, d: 134, r: 4 };          // breadboard
const BB_TOP = 9;
const PCB_Z = 15, PCB_H = 4, ZB = PCB_Z + PCB_H;                // DevKit PCB sits on black header strips
const PITCH = 6.35;
// board-local coordinates: xc runs from the antenna end (-64) to the USB end (+64); world x = -xc (USB end faces -x)
const wx = (xc) => -xc;
const pc = (xc, yc, w, d, r = 1) => ({ x: wx(xc) - w / 2, y: yc - d / 2, w, d, r });
const P3 = (xc, yc, z) => [wx(xc), yc, z];

// laptop (open at 90 degrees, screen facing the viewer)
const LAP = { x: -250, y: -56, w: 115, d: 100, r: 6 };
const LAP_Z = 0, LAP_H = 5;
const SCR_Y = LAP.y, SCR_T = 5, SCR_H = 80;
const SCR_FACE = SCR_Y + SCR_T;                                 // the visible +y face
const SCR = { x0: LAP.x + 7, x1: LAP.x + LAP.w - 7, z0: LAP_H + 10, z1: LAP_H + SCR_H - 7 };

const P = CLOSE
  ? k.fitProjection([...k.boxCorners({ x: -118, y: -52, w: 213, d: 122, r: 4 }, 0, 34)], WIDTH, HEIGHT, { pad: 12, azimuth: 54, elevation: 40 })
  : k.fitProjection(
    [...k.boxCorners(MAT, -MAT_H - FOOT_H, 0), [LAP.x, LAP.y, LAP_H + SCR_H + 4], [95, 60, 52], [-100, -60, 30]],
    WIDTH, HEIGHT, { pad: 22, azimuth: 60, elevation: 33 });
const at = (p) => k.iso(p, P);
const S = (paths, style) => k.solidSvg(paths, style);
const L = (d, style) => k.lineSvg(d, style);
const D = (points, style) => k.dotsSvg(points, style);
const V = G.viewOf(P);
const depth = (p) => k.depthOf(p, P);

const items = [];
const put = (key, svg) => { if (svg) items.push({ key, svg }); };

// ------------------------------------------------------------------ bench mat
function mat() {
  const out = [`<path class="iso-halo" d="${k.haloOf(MAT, -MAT_H - FOOT_H, MAT_H, P)}"/>`];
  const feet = k.corners(MAT, 20).sort((a, b) => depth([a[0], a[1], 0]) - depth([b[0], b[1], 0]));
  for (const [x, y] of feet) {
    out.push(S(k.cylinder(x, y, 7, -MAT_H - FOOT_H, 1.6, P, 28), { tone: "lo" }));
    out.push(S(k.cylinder(x, y, 5.4, -MAT_H - FOOT_H + 1.6, FOOT_H - 1.6, P, 28), { tone: "mid" }));
  }
  out.push(S(k.slabOf(MAT, -MAT_H, MAT_H, P, 8, 1.6), { tone: "mid" }));
  out.push(L(k.planOutline(k.insetPlan(MAT, 5), 0, P), { tone: "lo" }));
  const screws = k.corners(MAT, 10);
  out.push(L(screws.map(([x, y]) => k.ring(x, y, 2.2, 0, P, 16)).join(""), { tone: "lo" }));
  out.push(D(screws.map(([x, y]) => at([x, y, 0])), { size: 0.5 }));
  const strip = { x: -250, y: MAT.y + MAT.d - 16, w: 346, d: 7, r: 1 };
  out.push(S(k.slabOf(strip, 0, 0.6, P, 3), { tone: "lo", crease: "none" }));
  const ticks = k.topTicks(strip.x + 4, strip.x + strip.w - 4, 5, 5, strip.y + 0.8, 0.6, [2, 3.6], P);
  out.push(L(ticks.minor, { tone: "lo" }), L(ticks.major, { tone: "mid" }));
  out.push(D([at([strip.x + 2, strip.y + 3.5, 0.6]), at([strip.x + strip.w - 2, strip.y + 3.5, 0.6])], { size: 0.45 }));
  return out.join("");
}

// ------------------------------------------------------------------ breadboard
const COLS = Array.from({ length: 29 }, (_, i) => -88.9 + i * PITCH);
const STRIP_ROWS = [38, 44.35, 50.7];
const RAIL_ROWS = [58.2, 63.2];
function breadboard() {
  const out = [`<path class="iso-halo" d="${k.haloOf(BB, 0, BB_TOP, P)}" style="filter:blur(3px)"/>`];
  out.push(S(k.slabOf(BB, 0, BB_TOP, P, 4, 0.8), { tone: "hi", crease: "lo" }));
  const holes = [];
  for (const side of [1, -1]) {
    for (const row of STRIP_ROWS) for (const x of COLS) holes.push(at([x, side * row, BB_TOP]));
    for (const row of RAIL_ROWS) for (const x of COLS) if ((x + 88.9) / PITCH % 6 < 5) holes.push(at([x, side * row, BB_TOP]));
  }
  out.push(D(holes, { size: 0.32, tone: "lo" }));
  // centre channel, power-rail rules and the column letters/numbers engraved on the front edge
  for (const side of [1, -1]) {
    out.push(L(k.lineOnTop([-93, side * 3.4], [-70, side * 3.4], BB_TOP, P) + k.lineOnTop([70, side * 3.4], [93, side * 3.4], BB_TOP, P), { tone: "faint" }));
    out.push(L(k.lineOnTop([-91, side * 60.7], [91, side * 60.7], BB_TOP, P), { tone: "faint" }));
  }
  out.push(L(k.lineOnTop([-91, 55.6], [91, 55.6], BB_TOP, P) + k.lineOnTop([-91, -55.6], [91, -55.6], BB_TOP, P), { tone: "faint" }));
  [-1, 1].forEach((s, i) => out.push(k.faceTextSvg(k.topMatrix([-92, s * 59.4 + 0.9], BB_TOP, P, "x"), i ? "+  +  +" : "-  -  -", { size: 2.2, tone: "lo", anchor: "start" })));
  return out.join("");
}

// ------------------------------------------------------------------ ESP32 DevKit
const PIN_NAMES = ["EN", "VP", "VN", "34", "35", "32", "33", "25", "26", "27", "14", "12", "13", "GND", "VIN"];
const pinXc = (i) => -37 + i * PITCH;
const PIN_Y = 31.75;
const PIN_TOP = ZB + 3.6;

function board() {
  const out = [];
  const add = (key, svg) => out.push({ key, svg });
  const key = (xc, yc, z = ZB) => depth(P3(xc, yc, z));
  // header strips under the board: black plastic with the pin tails going into the breadboard
  for (const side of [1, -1]) {
    const hp = pc(7.5, side * PIN_Y, 95.4, 6.4, 0.6);
    add(-500 + (side > 0 ? 0 : -1), S(k.slabOf(hp, BB_TOP, PCB_Z - BB_TOP, P, 2, 0.3), { tone: "lo", crease: "faint" }));
  }
  add(-400, S(k.slabOf(pc(0, 0, 128, 71, 3), PCB_Z, PCB_H, P, 6, 0.6), { tone: "mid", crease: "faint" }));
  const top = [];
  const TP = (plan, h, tone, extra = {}, z = ZB) => S(k.slabOf(plan, z, h, P, extra.steps ?? 2, extra.bevel ?? 0.3), { tone, crease: extra.crease ?? "faint", inner: extra.inner, lit: extra.lit });
  const add2 = (xc, yc, svg, z = ZB) => top.push({ key: key(xc, yc, z), svg });

  // board outline silkscreen and name
  out.push({ key: -399, svg: L(k.planOutline(pc(0, 0, 123, 66, 2), ZB, P, 5), { tone: "faint" }) });
  out.push({ key: -398, svg: k.faceTextSvg(k.topMatrix(P3(16, -9, ZB), ZB, P, "x"), "ESP32 DEVKIT V1", { size: 3.1, tone: "lo", anchor: "middle" }) });

  // header pins (gold) and silkscreen pin names on the front row
  for (const side of [1, -1]) {
    PIN_NAMES.forEach((name, i) => {
      const xc = pinXc(i), yc = side * PIN_Y;
      const lit = side > 0 && (i === 3 || i === 4);
      add2(xc, yc, S(k.slabOf({ x: wx(xc) - 1.1, y: yc - 1.1, w: 2.2, d: 2.2, r: 0.25 }, ZB, 3.6, P, 1, 0.2), { tone: lit ? "hi" : "mid", crease: "none", lit }));
      if (side > 0) out.push({ key: -397, svg: k.faceTextSvg(k.topMatrix(P3(xc, 25.4, ZB), ZB, P, "x"), name, { size: 2.3, tone: lit ? "hi" : "lo", anchor: "middle" }) });
    });
  }

  // module PCB with the meandered PCB antenna and the metal shield
  const mod = pc(-32, 0, 64, 45, 1.2);
  add2(-32, 0, S(k.slabOf(mod, ZB, 2.5, P, 3, 0.4), { tone: "lo", crease: "faint" }));
  const antenna = [];
  const ys = [-18, -14, -10, -6, -2, 2, 6, 10, 14, 18];
  let dirRight = true; const path = [];
  ys.forEach((y) => { const a = dirRight ? -61 : -50; const b = dirRight ? -50 : -61; path.push([wx(a), y], [wx(b), y]); dirRight = !dirRight; });
  out.push({ key: key(-56, 0, ZB + 2.5) - 0.0, svg: L(k.onTop(path, ZB + 2.5, P), { tone: "mid" }) });
  out.push({ key: key(-56, 0, ZB + 2.5) + 0.01, svg: L(k.planOutline(pc(-56, 0, 15, 40, 0.6), ZB + 2.5, P, 2), { tone: "faint" }) });
  const pads = [];
  for (const s of [1, -1]) for (let i = 0; i < 9; i++) pads.push(at(P3(-4.5 - i * 4.2, s * 20.6, ZB + 2.5)));
  out.push({ key: key(-20, 0, ZB + 2.5) + 0.02, svg: D(pads, { size: 0.5 }) });

  const shield = pc(-23.5, 0, 46, 40, 1.4);
  add2(-23.5, 0, S(k.slabOf(shield, ZB + 2.5, 6.5, P, 3, 0.7), { tone: "hi", crease: "lo", inner: L(k.sideSeam(k.insetPlan(shield, 0.3), ZB + 5.2, P, 3), { tone: "faint" }) }), ZB + 4);
  const sTop = ZB + 9;
  add2(-23.5, 0, [
    L(k.planOutline(k.insetPlan(shield, 2.6), sTop, P, 3), { tone: "faint" }),
    k.faceTextSvg(k.topMatrix(P3(-23.5, -4, sTop), sTop, P, "x"), "ESP32-WROOM-32", { size: 3.4, tone: "mid", anchor: "middle" }),
    k.faceTextSvg(k.topMatrix(P3(-23.5, 2, sTop), sTop, P, "x"), "ESPRESSIF", { size: 2.6, tone: "lo", anchor: "middle" }),
    D(k.dotGrid(wx(-9.4), -14, 4, 3, -2.4, sTop, P).concat(), { size: 0.35, tone: "lo" }),
    L(k.lineOnTop([wx(-40), 10], [wx(-31), 10], sTop, P), { tone: "lo", free: true }),
    L(k.lineOnTop([wx(-40), 13], [wx(-35), 13], sTop, P), { tone: "faint", free: true }),
  ].join(""), sTop + 0.4);

  // CP2102 bridge, AMS1117 regulator, buttons, LEDs, passives
  add2(34, 0, [
    S(k.slabOf(pc(34, 0, 13, 13, 1), ZB, 3.2, P, 2, 0.4), { tone: "lo", crease: "faint" }),
    D([at(P3(37, 4.2, ZB + 3.2))], { size: 0.55 }),
    k.faceTextSvg(k.topMatrix(P3(33, -1.6, ZB + 3.2), ZB + 3.2, P, "x"), "CP2102", { size: 2.2, tone: "mid", anchor: "middle" }),
    k.faceTextSvg(k.topMatrix(P3(33, 2.2, ZB + 3.2), ZB + 3.2, P, "x"), "N", { size: 2.2, tone: "lo", anchor: "middle" }),
  ].join(""));
  for (const t of [-3.9, -1.3, 1.3, 3.9]) for (const s of [1, -1]) {
    add2(34 + s * 7.6, t, S(k.slabOf(pc(34 + s * 7.6, t, 2.4, 1.4, 0.3), ZB, 0.6, P, 1), { tone: "mid", crease: "none" }));
    add2(34 + t, s * 7.6, S(k.slabOf(pc(34 + t, s * 7.6, 1.4, 2.4, 0.3), ZB, 0.6, P, 1), { tone: "mid", crease: "none" }));
  }
  add2(12, 11, [
    S(k.slabOf(pc(21.5, 11, 7, 5.4, 0.6), ZB, 1.2, P, 1, 0.2), { tone: "mid", crease: "faint" }),
    S(k.slabOf(pc(12, 11, 11, 8, 0.8), ZB, 3.8, P, 2, 0.4), { tone: "lo", crease: "faint" }),
    ...[-2.6, 0, 2.6].map((dy) => S(k.slabOf(pc(5.3, 11 + dy, 2.2, 1.3, 0.2), ZB, 0.6, P, 1), { tone: "mid", crease: "none" })),
    k.faceTextSvg(k.topMatrix(P3(12, 11.8, ZB + 3.8), ZB + 3.8, P, "x"), "1117", { size: 2.4, tone: "mid", anchor: "middle" }),
  ].join(""));
  // micro-USB receptacle (its mouth faces -x, away from the viewer; the plug covers it anyway)
  const usb = pc(58, 0, 18, 15, 1);
  add2(58, 0, [
    S(k.slabOf(usb, ZB, 5.6, P, 2, 0.5), { tone: "hi", crease: "lo" }),
    L(k.planOutline(k.insetPlan(usb, 2), ZB + 5.6, P, 2), { tone: "faint" }),
    D([at(P3(52.5, -5.2, ZB + 5.6)), at(P3(52.5, 5.2, ZB + 5.6)), at(P3(63.5, -5.2, ZB + 5.6)), at(P3(63.5, 5.2, ZB + 5.6))], { size: 0.5 }),
  ].join(""), ZB + 4);
  for (const [name, yc] of [["EN", -21], ["BOOT", 21]]) {
    add2(44, yc, [
      S(k.slabOf(pc(44, yc, 15, 15, 1.6), ZB, 3, P, 3, 0.4), { tone: "lo", crease: "faint" }),
      D([at(P3(38.2, yc - 5.4, ZB + 3)), at(P3(38.2, yc + 5.4, ZB + 3)), at(P3(49.8, yc - 5.4, ZB + 3)), at(P3(49.8, yc + 5.4, ZB + 3))], { size: 0.4 }),
      S(k.cylinder(wx(44), yc, 4.4, ZB + 3, 2.4, P, 20, 0.4), { tone: "mid" }),
    ].join(""));
    out.push({ key: key(44, yc, ZB) + 0.02, svg: k.faceTextSvg(k.topMatrix(P3(44, yc + (yc < 0 ? 11.8 : -11.2), ZB), ZB, P, "x"), name, { size: 2.3, tone: "lo", anchor: "middle" }) });
  }
  const led = (xc, yc, on, label) => [
    S(k.slabOf(pc(xc, yc, 6, 3.6, 0.8), ZB, 2.2, P, 2, 0.3), { tone: on ? "hi" : "mid", crease: "faint" }),
    D([at(P3(xc - 2.1, yc, ZB + 2.2))], { size: 0.5 }),
  ].join("");
  add2(26, -22, led(26, -22, true));
  out.push({ key: key(26, -22) + 0.02, svg: k.faceTextSvg(k.topMatrix(P3(26, -17.8, ZB), ZB, P, "x"), "PWR", { size: 2, tone: "lo", anchor: "middle" }) });
  // GPIO2 user LED: two drawings, the page shows the one that matches the firmware state
  add2(26, 22, `<g data-part="led-off">${led(26, 22, false)}</g><g data-part="led-on" style="display:none">${S(k.slabOf(pc(26, 22, 6, 3.6, 0.8), ZB, 2.2, P, 2, 0.3), { tone: "lit", crease: "faint", lit: true })}${D([at(P3(23.9, 22, ZB + 2.2))], { size: 0.5, tone: "lit" })}</g>`);
  out.push({ key: key(26, 22) + 0.02, svg: k.faceTextSvg(k.topMatrix(P3(26, 17.8, ZB), ZB, P, "x"), "IO2", { size: 2, tone: "lo", anchor: "middle" }) });
  const passives = [[20, -16], [22, -10], [7, 17.5], [27, 9], [27, -9], [14, -20], [-2, 16], [-2, -16], [40, 8]];
  passives.forEach(([xc, yc]) => add2(xc, yc, S(k.slabOf(pc(xc, yc, 5, 3, 0.4), ZB, 1.6, P, 1, 0.2), { tone: "mid", crease: "none" })));
  return [...out, ...top].sort((a, b) => a.key - b.key).map((i) => i.svg).join("");
}

// ------------------------------------------------------------------ sensors on the breadboard
const LDR_C = [47.6, 49];             // body centre; legs in columns 44.45 and 50.8
const LDR_Z = BB_TOP + 7, LDR_R = 7.6, LDR_H = 4.4;
function ldr() {
  const [x, y] = LDR_C;
  const out = [];
  for (const lx of [44.45, 50.8]) {
    out.push(S(k.cylinder(lx, 50.7, 0.7, BB_TOP, LDR_Z - BB_TOP, P, 10), { tone: "mid", crease: "none" }));
    out.push(D([at([lx, 50.7, BB_TOP])], { size: 0.45 }));
  }
  out.push(S(k.cylinder(x, y, LDR_R, LDR_Z, LDR_H, P, 36, 0.4), { tone: "hi", crease: "lo", lit: true }));
  const top = LDR_Z + LDR_H;
  out.push(L(k.ring(x, y, LDR_R - 1.3, top, P, 36), { tone: "lo" }));
  // CdS serpentine track
  const pts = []; const rows = 9; const half = LDR_R - 2.5;
  for (let i = 0; i < rows; i++) {
    const yy = y - half + (2 * half * i) / (rows - 1);
    const w = Math.sqrt(Math.max(0.2, half * half - (yy - y) * (yy - y))) * 0.9;
    const a = [x + (i % 2 ? w : -w), yy], b = [x + (i % 2 ? -w : w), yy];
    pts.push(a, b);
  }
  out.push(L(k.onTop(pts, top, P), { tone: "hi" }));
  out.push(D([at([x - half * 0.9, y - half, top]), at([x + half * 0.9, y - half, top])], { size: 0.4, tone: "hi" }));
  return out.join("");
}

const POT_C = [-19, 49];
function pot() {
  const out = [];
  const body = { x: -30, y: 41.5, w: 22, d: 15, r: 1.6 };
  for (const lx of [-25.4, -19.05, -12.7]) {
    out.push(S(k.cylinder(lx, 50.7, 0.7, BB_TOP, 6, P, 10), { tone: "mid", crease: "none" }));
    out.push(D([at([lx, 50.7, BB_TOP])], { size: 0.45 }));
  }
  out.push(S(k.slabOf(body, BB_TOP + 5, 12, P, 3, 0.6), { tone: "mid", crease: "lo" }));
  out.push(D([at([-27.5, 43.8, BB_TOP + 17]), at([-10.5, 43.8, BB_TOP + 17]), at([-27.5, 54.2, BB_TOP + 17]), at([-10.5, 54.2, BB_TOP + 17])], { size: 0.4 }));
  const cx = -19, cy = 49, top = BB_TOP + 17;
  out.push(S(k.cylinder(cx, cy, 5.2, top, 2.4, P, 28, 0.4), { tone: "hi", crease: "lo" }));
  out.push(L(k.ring(cx, cy, 3.4, top + 2.4, P, 24), { tone: "faint" }));
  out.push(`<path data-part="pot-slot" class="iso-line" data-tone="hi" data-free="both" d="${potSlot(0.25)}" style="stroke-width:1.1"/>`);
  return out.join("");
}
const potSlot = (turn) => {
  const a = turn * Math.PI * 2, [cx, cy] = [-19, 49], z = BB_TOP + 19.4;
  return k.lineOnTop([cx - Math.cos(a) * 4.2, cy - Math.sin(a) * 4.2], [cx + Math.cos(a) * 4.2, cy + Math.sin(a) * 4.2], z, P);
};

// ------------------------------------------------------------------ jumper wires and the USB cable (3D tubes)
const pieces = [];
function route(points, radius, tone, { maxLength = 10, caps = true } = {}) {
  const smooth = G.fillet(points, 4.5, 7);
  for (const piece of T.tubePieces(smooth, radius, P, { maxLength, caps })) pieces.push({ key: G.dot3(piece.mid, V), svg: T.tubeSvg(piece, { tone }) });
}
function wires() {
  const pin = (i) => [wx(pinXc(i)), PIN_Y, PIN_TOP];
  route([pin(3), [pin(3)[0], PIN_Y, 34], [44.45, 38, 38], [44.45, 38, BB_TOP + 4]], 1.2, "hi");
  route([pin(4), [pin(4)[0], PIN_Y, 41], [-19.05, 38, 41], [-19.05, 38, BB_TOP + 4]], 1.2, "mid");
  route([pin(13), [pin(13)[0], PIN_Y, 30], [pin(13)[0] , 58.2, 30], [pin(13)[0], 58.2, BB_TOP + 4]], 1.2, "lo");
  const dots = [];
  for (const p of [pin(3), pin(4), pin(13), [44.45, 38, BB_TOP + 4], [-19.05, 38, BB_TOP + 4], [pin(13)[0], 58.2, BB_TOP + 4]]) dots.push(at(p));
  return D(dots, { size: 0.6, tone: "hi" });
}

const PLUG_Z = ZB + 3.6;
function plug() {
  const out = [];
  out.push(S(k.slabOf({ x: -79.2, y: -6.5, w: 11.6, d: 13, r: 1 }, PLUG_Z - 2.6, 4.4, P, 2, 0.3), { tone: "hi", crease: "lo" }));           // metal shell into the receptacle
  out.push(S(k.slabOf({ x: -96, y: -11, w: 17.5, d: 22, r: 4 }, PLUG_Z - 5.5, 11.5, P, 5, 0.8), { tone: "mid", crease: "lo" }));         // overmould
  out.push(L(k.lineOnTop([-93, -7], [-93, 7], PLUG_Z + 6, P) + k.lineOnTop([-90, -7], [-90, 7], PLUG_Z + 6, P) + k.lineOnTop([-87, -7], [-87, 7], PLUG_Z + 6, P), { tone: "faint" }));
  return out.join("");
}
function cable() {
  const pts = CLOSE ? [[-96, 0, PLUG_Z], [-106, 0, PLUG_Z - 2], [-112, 0, 9], [-117, 3, 3.2], [-121, 3, 3.2]] : [[-96, 0, PLUG_Z], [-106, 0, PLUG_Z - 2], [-112, 0, 9], [-118, 6, 3.2], [-124, PORT_Y, 3.2], [-132, PORT_Y, 3.2], [-136.8, PORT_Y, 2.6]];
  const smooth = G.fillet(pts, 9, 8);
  for (const piece of T.tubePieces(smooth, 2.4, P, { maxLength: 9, caps: [false, true], rings: { pitch: 4.5, tone: "faint" } })) pieces.push({ key: G.dot3(piece.mid, V), svg: T.tubeSvg(piece, { tone: "mid" }) });
}

// ------------------------------------------------------------------ laptop
function laptop() {
  const out = [];
  out.push(`<path class="iso-halo" d="${k.haloOf(LAP, LAP_Z, LAP_H, P)}" style="filter:blur(3px)"/>`);
  out.push(S(k.slabOf(LAP, LAP_Z, LAP_H, P, 6, 0.8), { tone: "mid", crease: "lo" }));
  // key caps: 4 rows of 12 plus a space bar, rows running along x
  const KX = LAP.x + 8, KY = LAP.y + 14, U = 8.6;
  [12, 12, 11, 10].forEach((n, r) => {
    for (let c = 0; c < n; c++) {
      const w = U * (12 / n);
      out.push(S(k.slabOf({ x: KX + c * w + 0.6, y: KY + r * 8.2, w: w - 1.2, d: 6.8, r: 1.2 }, LAP_H, 1.6, P, 2, 0.2), { tone: "lo", crease: "faint" }));
    }
  });
  out.push(S(k.slabOf({ x: KX + 20, y: KY + 4 * 8.2, w: 56, d: 6.8, r: 1.4 }, LAP_H, 1.6, P, 2, 0.2), { tone: "lo", crease: "faint" }));
  out.push(S(k.slabOf({ x: LAP.x + 40, y: LAP.y + 74, w: 36, d: 19, r: 3 }, LAP_H, 0.5, P, 3), { tone: "lo", crease: "none" }));
  // hinge barrel and the USB-A port on the +x side the cable arrives at
  out.push(S(k.slabOf({ x: LAP.x + 4, y: LAP.y + 5, w: LAP.w - 8, d: 7, r: 2 }, LAP_Z + LAP_H, 3.2, P, 3, 0.4), { tone: "hi", crease: "lo" }));
  out.push(S(k.slabOf({ x: LAP.x + LAP.w - 3.4, y: PORT_Y - 7, w: 3.4, d: 14, r: 0.6 }, 0.6, 3.6, P, 2), { tone: "lo", crease: "faint" }));
  // screen panel standing on the hinge
  out.push(S(k.slabOf({ x: LAP.x, y: SCR_Y, w: LAP.w, d: SCR_T, r: 2.4 }, LAP_Z + LAP_H, SCR_H, P, 4, 0.5), { tone: "hi", crease: "lo" }));
  return out.join("");
}
const PORT_Y = LAP.y + 52;

// the display window, drawn in the plane of the screen's +y face (local x along world x, local y down)
const planeOf = k.sideMatrix([0, SCR_FACE], 0, P, "left");
function screenStatic() {
  const shape = k.pathOf(k.roundedPlan({ x: SCR.x0, y: -SCR.z1, w: SCR.x1 - SCR.x0, d: SCR.z1 - SCR.z0, r: 2.5 }, 4), true);
  return `<g transform="${planeOf}"><path class="ac-glass" d="${shape}"/><path class="iso-line" data-tone="lo" d="${shape}"/></g>`;
}


// ------------------------------------------------------------------ live behaviour (same model as the simulator, PRD Part II 44)
const LIVE = `
const P = ${JSON.stringify(P)};
const SCR = ${JSON.stringify(SCR)}, FACE_X = ${JSON.stringify([SCR.x0, SCR.x1])};
const potSlot = ${potSlot.toString().replace("k.lineOnTop", "lineOnTop").replace("BB_TOP", String(BB_TOP))};
const stage = document.querySelector(".iso-stage"), svg = stage.querySelector("svg");
const live = svg.querySelector('[data-part="screen-live"]');
const ledOn = svg.querySelector('[data-part="led-on"]'), ledOff = svg.querySelector('[data-part="led-off"]');
const slot = svg.querySelector('[data-part="pot-slot"]');
const readout = document.querySelector("[data-readout]");
const still = matchMedia("(prefers-reduced-motion: reduce)");
const PRESETS = [
  { name: "nominal", interval: 50, load: 10, deadline: 10, sensor: "LDR" },
  { name: "seeded defect A", interval: 10, load: 70, deadline: 8, sensor: "LDR" },
  { name: "seeded defect C", interval: 5, load: 95, deadline: 10, sensor: "LDR" },
];
const BAR_N = 60, BAR_WINDOW = 24;
function rng(seed) { let a = seed >>> 0; return () => { a += 0x6D2B79F5; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
function run(c) {
  const r = rng(c.interval * 7919 + c.load * 104729 + c.deadline), gauss = () => Math.sqrt(-2 * Math.log(1 - r())) * Math.cos(2 * Math.PI * r());
  const overhead = { LDR: 120, POT: 150, ADC_SIM: 20 }[c.sensor];
  const defA = c.interval <= 15 && c.load >= 65, defC = c.interval <= 5 && c.load >= 90;
  const resetAt = defC ? 8 + Math.floor(r() * 20) : -1;
  const baseExec = 200 + c.load * 55 + overhead, out = []; let prev = 0;
  for (let i = 1; i <= BAR_N; i++) {
    const sched = i * c.interval * 1000; let exec = baseExec * (1 + 0.02 * gauss()), late = Math.abs(40 + c.load * 1.5 + 25 * gauss());
    if (defA) { exec *= 1 + 0.6 * (c.load - 65) / 35; if (r() < 0.3) late += -Math.log(1 - r()) * (3500 + (c.load - 65) * 80); }
    const start = Math.max(sched + late, prev); prev = start + exec;
    const missed = start + exec > sched + c.deadline * 1000;
    out.push({ ratio: (start + exec - sched) / (c.deadline * 1000), missed, start });
    if (i >= resetAt && resetAt > 0) return { samples: out, reset: true };
  }
  return { samples: out, reset: false };
}
function verdict(c, res) {
  const miss = res.samples.filter(s => s.missed).length;
  if (res.reset) return "WATCHDOG_RESET";
  if (miss > 0) return "TIMING_FAILURE";
  const iv = res.samples.slice(1).map((s, i) => (s.start - res.samples[i].start) / 1000), m = iv.reduce((a, b) => a + b, 0) / iv.length;
  const jit = Math.sqrt(iv.reduce((a, b) => a + (b - m) * (b - m), 0) / Math.max(1, iv.length - 1));
  return jit > Math.max(1.5, 0.25 * c.interval) ? "TIMING_FAILURE" : "PASS";
}
const BAR_BASE = SCR.z0 + 9, BAR_UNIT = 14;     // bar height of 1.0 (the deadline) in world units
const BAR_X0 = SCR.x0 + 6, BAR_W = (SCR.x1 - SCR.x0 - 12) / BAR_WINDOW;
function drawScreen(c, res, shown, text) {
  const win = res.samples.slice(Math.max(0, shown - BAR_WINDOW), shown);
  let ok = "", bad = "";
  win.forEach((s, i) => { const h = Math.max(0.6, Math.min(3.1, s.ratio) * BAR_UNIT), x = BAR_X0 + i * BAR_W; const d = "M" + x.toFixed(1) + " " + (-BAR_BASE) + "h" + (BAR_W - 1.2).toFixed(1) + "v" + (-h).toFixed(1) + "h" + (-(BAR_W - 1.2)).toFixed(1) + "Z"; if (s.missed) bad += d; else ok += d; });
  const top = -(SCR.z1) ;
  live.innerHTML = '<g><path class="ac-ok" d="' + ok + '"/><path class="ac-bad" d="' + bad + '"/>' +
    '<path class="ac-dl" d="M' + (BAR_X0 - 2) + " " + (-(BAR_BASE + BAR_UNIT)) + "H" + (BAR_X0 + BAR_WINDOW * BAR_W + 1) + '"/>' +
    '<path class="ac-base" d="M' + (BAR_X0 - 2) + " " + (-BAR_BASE) + "H" + (BAR_X0 + BAR_WINDOW * BAR_W + 1) + '"/>' +
    '<text class="ac-t" x="' + BAR_X0 + '" y="' + (top + 9) + '" font-size="4.6">EXP 101  RUN_TIMING_TEST</text>' +
    '<text class="ac-t2" x="' + BAR_X0 + '" y="' + (top + 17) + '" font-size="3.5">' + text + '</text>' +
    '</g>';
}
let preset = 0, runData = run(PRESETS[0]), shown = 1, last = 0, acc = 0, hold = 0, tour = true, blink = 0, turn = 0.25;
const label = () => { const c = PRESETS[preset], miss = runData.samples.slice(0, shown).filter(s => s.missed).length; const done = shown >= runData.samples.length;
  const v = done ? verdict(c, runData) : "running";
  return { screen: c.interval + " ms · load " + c.load + " · dl " + c.deadline + " ms · " + miss + "/" + shown + " missed", read: "interval " + c.interval + " ms · load " + c.load + " · " + miss + "/" + shown + " missed · " + v + (done && c.name !== "nominal" ? " (" + c.name + ")" : "") }; };
function paint() { const l = label(); drawScreen(PRESETS[preset], runData, shown, l.screen); if (readout.textContent !== l.read) readout.textContent = l.read;
  stage.setAttribute("aria-valuetext", l.read); }
function setPreset(i) { preset = (i + PRESETS.length) % PRESETS.length; runData = run(PRESETS[preset]); shown = 1; hold = 0; paint(); }
function tick(now) {
  const dt = last ? Math.min((now - last) / 1000, 0.05) : 0.016; last = now;
  if (!still.matches) {
    acc += dt; turn += dt * 0.04; slot.setAttribute("d", potSlot(turn));
    if (acc > 0.2) { acc = 0; if (shown < runData.samples.length) { shown++; blink = 0.1; paint(); } else { hold += 0.2; if (tour && hold > 2.4) setPreset(preset + 1); } }
    if (blink > 0) { blink -= dt; ledOn.style.display = ""; ledOff.style.display = "none"; } else { ledOn.style.display = "none"; ledOff.style.display = ""; }
  }
  requestAnimationFrame(tick);
}
stage.addEventListener("pointerdown", () => { tour = false; setPreset(preset + 1); });
stage.addEventListener("keydown", (e) => { if (e.key === "ArrowRight" || e.key === "ArrowUp") { tour = false; setPreset(preset + 1); } if (e.key === "ArrowLeft" || e.key === "ArrowDown") { tour = false; setPreset(preset - 1); } });
if (still.matches) { shown = runData.samples.length; }
paint();
requestAnimationFrame(tick);
`;

const CSS_EXTRA = `.ac-glass{fill:#07090b}.ac-ok{fill:#7f8b96}.ac-bad{fill:var(--anatomy-red)}.ac-dl{stroke:#c9ced3;stroke-width:.5;stroke-dasharray:2 1.4;fill:none}.ac-base{stroke:#56606a;stroke-width:.5;fill:none}.ac-t{fill:#dfe4e8;font-family:var(--anatomy-mono)}.ac-t2{fill:#8f99a3;font-family:var(--anatomy-mono)}`;

// ------------------------------------------------------------------ assemble
const wireDots = wires();
cable();
if (!CLOSE) put(depth([-95, 0, 0]), laptop());
put(depth([-20, 0, 2]), breadboard());
put(depth([0, 0, 30]), board());
put(depth([-84, 0, 20]), plug());
put(depth([...LDR_C, 14]), ldr());
put(depth([...POT_C, 20]), pot());
for (const p of pieces) items.push(p);
items.sort((a, b) => a.key - b.key);

const body = [CLOSE ? "" : mat(), items.map((i) => i.svg).join(""), `<g data-part="wire-dots">${wireDots}</g>`,
  CLOSE ? "" : `<g data-part="screen">${screenStatic()}<g data-part="screen-live" transform="${planeOf}"></g></g>`].join("");

export const svg = k.figureSvg({
  width: WIDTH, height: HEIGHT,
  label: "The ChipCheck timing bench. A laptop on the left is connected by a USB cable to an ESP32-WROOM-32 DevKit mounted on a breadboard. A photoresistor is wired to GPIO34 and a trimmer to GPIO35. The laptop screen shows the lateness of each sampled task against its deadline.",
  body,
});
export { P, theme, kitScript, k, WIDTH, HEIGHT, SCR, SCR_FACE, planeOf, potSlot, LDR_C, POT_C, BB_TOP };
if (process.argv[1] && process.argv[1].endsWith("bench.build.mjs")) {
  const plate = k.plateHtml(CLOSE ? { fig: "Fig 2", title: "ESP32-WROOM-32 DevKit", hint: "", readout: "GPIO34 · LDR  GPIO35 · trimmer  USB · JSONL @ 115200", keys: [{ mark: "lit", label: "GPIO34 and GPIO35 header pins carrying the sensor signals" }, { mark: "raised", label: "ESP32-WROOM-32 module, CP2102 USB bridge, AMS1117 regulator" }], caption: "ESP32-WROOM-32 DevKit (30-pin) on a breadboard: PCB-antenna module under its metal shield, CP2102 USB-UART bridge, AMS1117 3.3 V regulator, EN and BOOT buttons, power and GPIO2 LEDs. A photoresistor feeds GPIO34 and a trimmer GPIO35; both jumpers and the ground lead are drawn, the 3.3 V feed and pull-down resistor are omitted.", body: `<div class="iso-stage">${svg}</div>` } : { fig: "Fig 1", title: "Timing bench", hint: "Click or press an arrow key to change the experiment", readout: "", keys: [{ mark: "lit", label: "Photoresistor on GPIO34: the sensor under test" }, { mark: "raised", label: "Laptop, USB cable, ESP32 DevKit and breadboard" }, { mark: "red", label: "A sample whose completion passed scheduled time plus deadline" }], caption: "The software side runs on the laptop and talks JSON Lines over USB to the ESP32. The screen draws, for each task release, how long after its scheduled time the task finished compared with the deadline (dashed line). Bars come from the same timing model as the project simulator (seeded defects A and C), not from a board; noise is not the simulator's.", body: `<div class="iso-stage" tabindex="0" role="img" aria-label="Timing bench: arrow keys change the experiment">${svg}</div>` });
  const page = k.pageHtml({ title: "ChipCheck timing bench", theme, width: 1040, body: plate + `<style>${CSS_EXTRA}</style>`, script: kitScript() + (CLOSE ? "" : LIVE) });
  writeFileSync(join(HERE, `${CLOSE ? "devkit" : "bench"}${theme === "light" ? "-light" : ""}.html`), page);
  console.log("wrote", theme, "svg bytes", svg.length, "items", items.length);
}
