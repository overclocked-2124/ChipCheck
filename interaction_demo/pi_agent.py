#!/usr/bin/env python3
"""Raspberry Pi side of the ChipCheck interaction demo. Copy this one file to the Pi.

    python3 pi_agent.py                                # real GPIO (needs: sudo apt install python3-gpiozero)
    python3 pi_agent.py --fake                         # no GPIO, for testing the link

The laptop sends POST /run with three 0-255 values. The agent sets them as PWM duty on the LED pins,
listens for the buzzer on a digital sound-sensor pin, and replies with the measurements.
Every duty is forced to 0 on start, on any error and on exit. Nothing here is a reviewed safety limit.
"""
import argparse, hmac, json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fault_injection import buzzer_should_sound, describe  # the injected fault; keep this file next to pi_agent.py

LOCK = threading.Lock()


class Bench:
    def __init__(self, leds, sensor, fake, buzzer=0):
        self.fake = fake
        self.sensor = None
        self.buzzer = None
        self.duty = [0, 0, 0]
        if fake:
            return
        from gpiozero import DigitalInputDevice, PWMLED  # imported late so --fake works anywhere
        self.leds = [PWMLED(p, frequency=1000) for p in leds]
        # No sensor wired yet: the LEDs are real, the buzzer verdict comes from the stand-in rules.
        self.sensor = DigitalInputDevice(sensor, pull_up=False) if sensor else None
        # An active buzzer that is ALWAYS driven on; the injected fault is what switches it off.
        from gpiozero import OutputDevice
        self.buzzer = OutputDevice(buzzer, initial_value=False) if buzzer else None
        self.safe()

    def safe(self):
        self.duty = [0, 0, 0]
        if not self.fake:
            for led in self.leds:
                led.value = 0
            if self.buzzer is not None:
                self.buzzer.off()

    def run(self, values, settle=0.4, window=0.6):
        self.duty = list(values)
        if self.fake:
            time.sleep(settle + window)
            return fake_sound(values), 62.5 if fake_sound(values) else 0.0
        for led, v in zip(self.leds, values):
            led.value = v / 255
        if self.buzzer is not None:  # the DUT: always buzzing, except where the fault is injected
            self.buzzer.value = 1 if buzzer_should_sound(*values) else 0
        time.sleep(settle)
        high = total = 0
        end = time.monotonic() + window
        while time.monotonic() < end:  # a sound module pulses its output while it hears a tone
            high += 1 if self.sensor is not None and self.sensor.value else 0
            total += 1
            time.sleep(0.002)
        commanded = fake_sound(values)       # what the injected fault tells the buzzer to do
        share = high / max(total, 1)
        self.safe()
        if self.sensor is None:              # no sensor wired: report the commanded state
            return commanded, 62.5 if commanded else 0.0
        return share > 0.05, round(share, 3)


def fake_sound(v):
    """What the buzzer does under the injected fault (see fault_injection.py)."""
    return buzzer_should_sound(*v)


def make_handler(bench, token):
    class H(BaseHTTPRequestHandler):
        def reply(self, code, payload):
            data = json.dumps(payload).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def authed(self):
            got = self.headers.get("Authorization", "")
            return hmac.compare_digest(got, f"Bearer {token}")

        def do_GET(self):
            if self.path == "/health" and self.authed():
                return self.reply(200, {"ok": True, "fake": bench.fake, "duty": bench.duty})
            self.reply(401 if not self.authed() else 404, {"error": "unauthorised or not found"})

        def do_POST(self):
            if not self.authed():
                return self.reply(401, {"error": "bad token"})
            if self.path != "/run":
                return self.reply(404, {"error": "not found"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size > 4000: raise ValueError("request too large")
                cmd = json.loads(self.rfile.read(size))
                p = cmd["parameters"]
                vals = [p[f"led{i}_value"] for i in (1, 2, 3)]
                if any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 255 for v in vals):
                    raise ValueError("led values must be integers 0-255")
                t0 = time.monotonic()
                with LOCK:
                    heard, level = bench.run(vals)
                print(f"[{time.strftime('%H:%M:%S')}] run #{cmd.get('experiment_id', '?')} LED {vals[0]}/{vals[1]}/{vals[2]} "
                      f"duty {round(vals[0] / 2.55)}%/{round(vals[1] / 2.55)}%/{round(vals[2] / 2.55)}% -> "
                      f"{'PASS' if heard else 'FAIL'} buzzer {'rings' if heard else 'silent'} level {level} "
                      f"({time.monotonic() - t0:.2f}s, {'sensor' if bench.sensor is not None else 'simulated buzzer'}) "
                      f"from {self.address_string()}", flush=True)
                out = {"applied_parameters": {f"led{i + 1}_value": v for i, v in enumerate(vals)},
                       "measurements": {"buzzer_detected": bool(heard), "sound_level": level, "frequency_hz": 2000 if heard else 0},
                       "outcome": "PASS" if heard else "FAIL", "measurement_quality": "VALID",
                       "source": "fake" if bench.fake else ("raspberry-pi" if bench.sensor is not None else ("raspberry-pi (LEDs and buzzer real, fault injected)" if bench.buzzer is not None else "raspberry-pi (LEDs real, buzzer simulated)"))}
                self.reply(200, out)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
                bench.safe(); self.reply(400, {"error": str(e)})
            except Exception as e:  # hardware fault: go safe, report it
                bench.safe(); self.reply(500, {"error": f"hardware error: {e}"})

        def log_message(self, fmt, *args):
            if "/health" not in (fmt % args):  # the page polls /health every few seconds; keep the log readable
                print("%s %s" % (self.address_string(), fmt % args), flush=True)
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default="demo", help="shared secret, default 'demo' (same default on the laptop); change it on both sides to lock it down")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--leds", default="18,13,19", help="BCM pins for LED 1,2,3 (PWM-capable: 12,13,18,19)")
    ap.add_argument("--sensor", type=int, default=0, help="BCM pin wired to the sound sensor's digital output; 0 (default) means no sensor yet, so the buzzer verdict is simulated while the LEDs are real")
    ap.add_argument("--buzzer", type=int, default=0, help="BCM pin for an ACTIVE buzzer (+ to the pin, - to GND). The agent keeps it buzzing except where the fault is injected. 0 = none")
    ap.add_argument("--fake", action="store_true", help="no GPIO; stand-in device for testing the link")
    a = ap.parse_args()
    bench = Bench([int(x) for x in a.leds.split(",")], a.sensor, a.fake, a.buzzer)
    print(describe(), flush=True)
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(bench, a.token))
    print(f"pi agent on {a.host}:{a.port} ({'FAKE' if a.fake else 'GPIO'}); leds {a.leds}, sensor {a.sensor}", flush=True)
    try:
        srv.serve_forever()
    finally:
        bench.safe()


if __name__ == "__main__":
    main()
