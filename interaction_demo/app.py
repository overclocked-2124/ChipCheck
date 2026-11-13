"""Local-only demo server: python -m interaction_demo.app."""
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse
from interaction_demo.core import Campaign
from interaction_demo.simulator import execute as simulate
from interaction_demo import pi_executor

def execute(command):
    """Real Raspberry Pi if CHIPCHECK_PI_URL is set, otherwise the simulator."""
    return pi_executor.execute(command) if os.environ.get('CHIPCHECK_PI_URL') else simulate(command)


ROOT = Path(__file__).parent
PORT = int(os.environ.get('CHIPCHECK_DEMO_PORT', '8767'))
HOST = os.environ.get('CHIPCHECK_DEMO_HOST', '127.0.0.1')   # 0.0.0.0 to reach it over the hotspot
DB = Path(os.environ.get('CHIPCHECK_DEMO_DB', str(Path.home()/'.local/share/chipcheck/interaction-demo.sqlite3')))
DB.parent.mkdir(parents=True, exist_ok=True)

def page():
    html = (ROOT/'index.html').read_text(encoding='utf-8'); fig = ROOT/'bench_figure.html'
    return html.replace('<!--BENCH_FIGURE-->', fig.read_text(encoding='utf-8') if fig.exists() else '').encode()

def probe(data):
    """Manual what-if on the simulator. Not stored and not counted against any campaign budget."""
    vals = {}
    for i in (1, 2, 3):
        v = data.get(f'led{i}')
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 255: raise ValueError(f'led{i} must be an integer 0-255')
        vals[f'led{i}_value'] = v
    return execute({'campaign_id': 'manual', 'batch_id': 'manual', 'experiment_id': 'manual', 'parameters': vals})

class Handler(BaseHTTPRequestHandler):
    def reply(self, code, payload, content='application/json'):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code); self.send_header('Content-Type', content); self.send_header('Content-Length', str(len(data))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/': return self.reply(200, page(), 'text/html; charset=utf-8')
        if path == '/api/mode':
            url = os.environ.get('CHIPCHECK_PI_URL')
            if not url: return self.reply(200, {'mode': 'simulator'})
            try:
                import urllib.request
                req = urllib.request.Request(url.rstrip('/') + '/health', headers={'Authorization': 'Bearer ' + os.environ.get('CHIPCHECK_PI_TOKEN', '')})
                with urllib.request.urlopen(req, timeout=2) as r: info = json.loads(r.read())
                return self.reply(200, {'mode': 'pi', 'reachable': True, 'fake': info.get('fake', False), 'url': url})
            except Exception as e: return self.reply(200, {'mode': 'pi', 'reachable': False, 'url': url, 'error': str(e)})
        if path.startswith('/api/campaign/'):
            try: return self.reply(200, Campaign(DB).state(path.rsplit('/',1)[-1]))
            except ValueError as e: return self.reply(400, {'error':str(e)})
        self.reply(404, {'error':'Not found'})
    def do_POST(self):
        try:
            if self.headers.get('Origin') not in (None, f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}', f"http://{self.headers.get('Host')}"): raise ValueError('Invalid origin')
            size = int(self.headers.get('Content-Length','0'))
            if size > 10000: raise ValueError('Request too large')
            data = json.loads(self.rfile.read(size))
            if self.path == '/api/probe': return self.reply(200, probe(data))
            c = Campaign(DB)
            if self.path == '/api/create':
                cid = c.create(data['planner'], int(data['budget']), int(data['seed'])); result = c.state(cid)
            elif self.path == '/api/propose': result = c.propose(data['id'], int(data['count']), data.get('purpose','explore'))
            elif self.path == '/api/run': result = c.run_pending(data['id'], executor=execute)
            else: return self.reply(404, {'error':'Not found'})
            self.reply(200,result)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e: self.reply(400, {'error':str(e)})

if __name__ == '__main__':
    print(f'ChipCheck demo on http://{HOST}:{PORT} ({"Raspberry Pi at " + os.environ["CHIPCHECK_PI_URL"] if os.environ.get("CHIPCHECK_PI_URL") else "simulator"})', flush=True)
    HTTPServer((HOST,PORT),Handler).serve_forever()
