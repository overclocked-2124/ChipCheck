"""Draws the three IEEE-style slide figures (transparent background, grayscale, Times-compatible font, no legend).
Run: python3 make_figures_ieee.py
Outputs: fig1-methodology-flow.png, fig2-system-architecture.png, fig3-microservice-architecture.png  (+ @1x copies)"""
from PIL import Image, ImageDraw, ImageFont
import math

S = 4                      # supersampling; outputs are downscaled by 2 (final = 2x logical), @1x by 4
FD = "/usr/share/fonts/truetype/liberation/LiberationSerif-"
def F(sz, style="Regular"): return ImageFont.truetype(FD + style + ".ttf", int(sz * S))
LW = 3
INK, FILL, SHADE, DEC, BAND = "#000000", "#FFFFFF", "#E3E3E3", "#F3F3F3", "#F6F6F6"

class Fig:
    def __init__(self, w=1900, h=1100):
        self.im = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0)); self.d = ImageDraw.Draw(self.im)
    P = staticmethod(lambda pts: [(x * S, y * S) for x, y in pts])
    def text(self, x, y, s, size, style="Regular", anchor="mm"):
        self.d.text((x * S, y * S), s, font=F(size, style), fill=INK, anchor=anchor)
    def block(self, cx, cy, lines, size=27, bold_n=1):
        g = size * 1.28; y = cy - len(lines) * g / 2 + g / 2
        for i, ln in enumerate(lines):
            self.text(cx, y, ln, size, "Bold" if i < bold_n else "Regular"); y += g
    def process(self, cx, cy, w, h, lines, fill=FILL, size=27, bold_n=1):
        self.d.rectangle(self.P([(cx - w / 2, cy - h / 2), (cx + w / 2, cy + h / 2)]), fill=fill, outline=INK, width=LW * S)
        self.block(cx, cy, lines, size, bold_n)
    def term(self, cx, cy, w, h, lines):
        self.d.rounded_rectangle(self.P([(cx - w / 2, cy - h / 2), (cx + w / 2, cy + h / 2)]), radius=(h / 2) * S, fill=SHADE, outline=INK, width=LW * S)
        self.block(cx, cy, lines)
    def decision(self, cx, cy, w, h, lines, bold_n=None):
        pts = [(cx, cy - h / 2), (cx + w / 2, cy), (cx, cy + h / 2), (cx - w / 2, cy)]
        self.d.polygon(self.P(pts), fill=DEC); self.d.line(self.P(pts + [pts[0]]), fill=INK, width=LW * S, joint="curve")
        self.block(cx, cy, lines, 26, len(lines) if bold_n is None else bold_n)
    def cylinder(self, cx, cy, w, h, lines, fill=FILL):
        e = 26; x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
        self.d.rectangle(self.P([(x0, y0 + e / 2), (x1, y1 - e / 2)]), fill=fill)
        self.d.ellipse(self.P([(x0, y1 - e), (x1, y1)]), fill=fill, outline=INK, width=LW * S)
        self.d.rectangle(self.P([(x0 + 2, y1 - e - 4), (x1 - 2, y1 - e / 2 - 1)]), fill=fill)
        self.d.line(self.P([(x0, y0 + e / 2), (x0, y1 - e / 2)]), fill=INK, width=LW * S)
        self.d.line(self.P([(x1, y0 + e / 2), (x1, y1 - e / 2)]), fill=INK, width=LW * S)
        self.d.ellipse(self.P([(x0, y0), (x1, y0 + e)]), fill=fill, outline=INK, width=LW * S)
        self.block(cx, cy + 8, lines)
    def rect_dashed(self, x0, y0, x1, y1, width=2, fill=None):
        if fill: self.d.rectangle(self.P([(x0, y0), (x1, y1)]), fill=fill)
        for a, b in [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]:
            self._dash(self.P([a, b]), width)
    def band(self, x0, y0, x1, y1, label, align="l"):
        self.d.rectangle(self.P([(x0, y0), (x1, y1)]), fill=BAND, outline=INK, width=2 * S)
        if align == "l": self.text(x0 + 22, y0 + 28, label, 27, "Bold", "lm")
        else: self.text(x1 - 22, y0 + 28, label, 27, "Bold", "rm")
    def _dash(self, Q, width, seg=14):
        for a, b in zip(Q, Q[1:]):
            n = max(1, int(math.dist(a, b) / (seg * S)))
            for i in range(0, n, 2):
                p = (a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)
                q = (a[0] + (b[0] - a[0]) * (i + 1) / n, a[1] + (b[1] - a[1]) * (i + 1) / n)
                self.d.line([p, q], fill=INK, width=width * S)
    def arrow(self, pts, dashed=False, both=False):
        Q = self.P(pts)
        if dashed: self._dash(Q, LW)
        else:
            for a, b in zip(Q, Q[1:]): self.d.line([a, b], fill=INK, width=LW * S)
        def head(p0, p1):
            (x0, y0), (x1, y1) = p0, p1; a = math.atan2(y1 - y0, x1 - x0); L, W = 24 * S, 9 * S
            self.d.polygon([(x1, y1), (x1 - L * math.cos(a) + W * math.sin(a), y1 - L * math.sin(a) - W * math.cos(a)),
                            (x1 - L * math.cos(a) - W * math.sin(a), y1 - L * math.sin(a) + W * math.cos(a))], fill=INK)
        head(Q[-2], Q[-1])
        if both: head(Q[1], Q[0])
    def tag(self, x, y, s, anchor="mm", size=25): self.text(x, y, s, size, "Italic", anchor)
    def save(self, name):
        bbox = self.im.getchannel("A").getbbox(); pad = 22 * S
        im = self.im.crop((max(bbox[0] - pad, 0), max(bbox[1] - pad, 0), min(bbox[2] + pad, self.im.width), min(bbox[3] + pad, self.im.height)))
        down = lambda k: im.convert("RGBa").resize((im.width // k, im.height // k), Image.LANCZOS).convert("RGBA")
        big = down(2); big.save(name + ".png"); down(4).save(name + "@1x.png"); print(name, big.size)

# =============================================================== Fig. 1  methodology
f = Fig(1900, 1080)
f.term(90, 240, 150, 66, ["Start"])
f.process(380, 240, 300, 150, ["1. Define test rules", "what can change, safe", "limits, what is a failure"])
f.process(760, 240, 320, 150, ["2. AI planner selects", "the next experiment", "from all past results"], SHADE)
f.decision(1150, 240, 372, 230, ["3. Within safe limits?", "(checked twice)"], bold_n=1)
f.process(1560, 240, 340, 170, ["4. Run on the board", "and measure voltage,", "current, timing, heartbeat,", "reset and OLED response"])
f.arrow([(165, 240), (228, 240)]); f.arrow([(530, 240), (598, 240)])
f.arrow([(920, 240), (962, 240)]); f.arrow([(1336, 240), (1388, 240)]); f.tag(1362, 214, "Yes")
f.arrow([(1150, 125), (1150, 96), (760, 96), (760, 163)], dashed=True)
f.tag(955, 72, "No: rejected, planner selects another")
f.decision(1560, 545, 340, 220, ["5. Measurements", "trustworthy?"])
f.decision(1150, 545, 340, 220, ["6. Requirement", "violated?"])
f.process(760, 545, 320, 150, ["7. Repeat to confirm,", "then reduce to the", "simplest cause"], SHADE)
f.term(330, 545, 360, 100, ["End: failure found", "report with evidence"])
f.arrow([(1560, 325), (1560, 435)])
f.arrow([(1388, 545), (1322, 545)]); f.tag(1355, 519, "Yes")
f.arrow([(978, 545), (922, 545)]); f.tag(950, 519, "Yes")
f.arrow([(598, 545), (512, 545)])
f.decision(1150, 825, 340, 200, ["8. Experiment", "budget left?"])
f.process(1560, 825, 340, 130, ["Mark as invalid:", "not used for learning,", "still uses budget"], SHADE)
f.term(1150, 1022, 520, 66, ["End: no failure found within budget"])
f.arrow([(1150, 655), (1150, 725)]); f.tag(1170, 692, "No", "lm")
f.arrow([(1560, 655), (1560, 760)]); f.tag(1580, 708, "No", "lm")
f.arrow([(1388, 825), (1322, 825)])
f.arrow([(1150, 925), (1150, 988)]); f.tag(1170, 957, "No", "lm")
f.arrow([(978, 825), (60, 825), (60, 372), (700, 372), (700, 316)], dashed=True)
f.tag(520, 797, "Yes: learn from the result, run the next experiment")
f.d.rectangle(f.P([(40, 925), (800, 1045)]), outline=INK, width=2 * S)
f.text(420, 962, "Safety at every step", 28, "Bold")
f.text(420, 1002, "Hardware watchdog, fuse and E-stop cut power independently;", 24)
f.text(420, 1030, "a safety trip stops testing until manually reviewed.", 24)
f.save("fig1-methodology-flow")

# =============================================================== Fig. 2  system architecture
f = Fig(1920, 1100)
f.band(40, 30, 1880, 370, "Control plane: application on the laptop")
f.band(40, 430, 1880, 1060, "Bench plane: beside the physical hardware", align="r")
bw, bh, X = 350, 150, [270, 730, 1190, 1650]
cy = 205
f.process(X[0], cy, bw, bh, ["Planner", "Agent + Decision:", "proposes the next", "experiment"], SHADE, 26)
f.process(X[1], cy, bw, bh, ["Backend + database", "campaign state, rules,", "safety check 1"], FILL, 26)
f.process(X[2], cy, bw, bh, ["Web console", "contract review, arming,", "live status, reports"], FILL, 26)
f.process(X[3], cy, bw, bh, ["Researcher", "configures, arms,", "monitors, reviews"], FILL, 26)
f.arrow([(X[0] + bw / 2, cy), (X[1] - bw / 2, cy)]); f.tag((X[0] + X[1]) / 2, cy - 24, "candidate", size=23)
f.arrow([(X[2] - bw / 2, cy), (X[1] + bw / 2, cy)]); f.arrow([(X[3] - bw / 2, cy), (X[2] + bw / 2, cy)])
r1, r2 = 640, 880
f.process(X[1], r1, bw, bh, ["Controller", "runs the experiment,", "safety check 2"], FILL, 26)
f.process(X[2], r1, bw, bh, ["Adapter", "translates commands for", "each instrument"], FILL, 26)
f.process(X[3], r1, bw, bh, ["Test-controller MCU", "exact timing, watchdog"], FILL, 26)
f.process(X[1], r2, bw, bh, ["Hardware safety", "E-stop, fuse, power cutoff"], SHADE, 26)
f.process(X[2], r2, bw, bh, ["Programmable rails", "voltage and current", "measurement"], FILL, 26)
f.process(X[3], r2, bw, bh, ["ESP32 DUT", "OLED, sensor, LEDs"], SHADE, 26)
f.arrow([(680, cy + bh / 2), (680, r1 - bh / 2)]); f.tag(668, 400, "approved episode", "rm", 23)
f.arrow([(780, r1 - bh / 2), (780, cy + bh / 2)], dashed=True); f.tag(792, 400, "results + evidence", "lm", 23)
f.arrow([(X[1] + bw / 2, r1), (X[2] - bw / 2, r1)]); f.arrow([(X[2] + bw / 2, r1), (X[3] - bw / 2, r1)])
f.arrow([(X[2], r1 + bh / 2), (X[2], r2 - bh / 2)]); f.tag(X[2] + 14, (r1 + r2) / 2, "set and read rails", "lm", 23)
f.arrow([(X[3], r1 + bh / 2), (X[3], r2 - bh / 2)]); f.tag(X[3] + 14, (r1 + r2) / 2, "workloads", "lm", 23)
f.arrow([(X[2] + bw / 2, r2), (X[3] - bw / 2, r2)]); f.tag((X[2] + X[3]) / 2, r2 - 26, "power", size=23)
f.arrow([(X[1] + bw / 2, r2), (X[2] - bw / 2, r2)]); f.tag((X[1] + X[2]) / 2, r2 - 26, "cutoff", size=23)
f.arrow([(X[3] + bw / 2, r1), (1850, r1), (1850, 1032), (X[1], 1032), (X[1], r2 + bh / 2)], dashed=True)
f.tag(1250, 1010, "watchdog heartbeat", size=23)
f.process(285, 760, 450, 300, ["Four safety layers", "1. Backend checks the limits", "2. Controller re-checks the", "    bench before running", "3. Instrument limits", "4. Watchdog, fuse, E-stop"], FILL, 25)
f.save("fig2-system-architecture")

# =============================================================== Fig. 3  microservice architecture
f = Fig(1900, 1100)
f.rect_dashed(790, 20, 1790, 235)                      # agent worker process
f.tag(1290, 215, "Agent worker process", size=23)
f.process(1010, 115, 340, 130, ["Agent Service", "campaign lifecycle, budget,", "confirmation, minimization"], FILL, 24)
f.process(1570, 115, 340, 130, ["Decision Service", "planner algorithms:", "baselines + adaptive"], SHADE, 24)
f.process(440, 130, 340, 120, ["Console", "Next.js, React, TypeScript"], FILL, 24)
f.process(440, 420, 340, 120, ["BFF Service", "session and request shaping"], FILL, 24)
f.process(1010, 420, 420, 170, ["Backend Service", "authorization, contract, campaign", "state, episode leases,", "safety check 1"], SHADE, 24)
f.cylinder(1570, 420, 300, 150, ["PostgreSQL +", "trace storage"])
f.rect_dashed(790, 580, 1790, 810)                     # local bench process
f.tag(1290, 790, "Local bench process", size=23)
f.process(1010, 675, 340, 130, ["Controller Service", "episode state machine,", "safety check 2"], FILL, 24)
f.process(1570, 675, 340, 130, ["Adapter Service", "instrument drivers"], FILL, 24)
f.process(1570, 960, 400, 130, ["Firmware", "test-controller MCU, ESP32 DUT"], SHADE, 24)
f.arrow([(440, 190), (440, 360)], both=False); f.tag(456, 275, "gRPC / protobuf", "lm", 23)
f.arrow([(610, 420), (800, 420)]); f.tag(705, 394, "gRPC", size=23)
f.arrow([(1010, 180), (1010, 335)], both=True); f.tag(1026, 258, "read history, submit candidate", "lm", 23)
f.arrow([(1180, 115), (1400, 115)], both=True); f.tag(1290, 84, "context / candidate", size=22)
f.arrow([(1220, 420), (1420, 420)], both=True)
f.arrow([(1010, 505), (1010, 610)], both=True); f.tag(1026, 556, "claim episode, submit results", "lm", 23)
f.arrow([(1180, 675), (1400, 675)]); f.tag(1290, 647, "generic operations", size=22)
f.arrow([(1570, 740), (1570, 895)]); f.tag(1586, 856, "USB / serial / LAN", "lm", 23)
f.save("fig3-microservice-architecture")
