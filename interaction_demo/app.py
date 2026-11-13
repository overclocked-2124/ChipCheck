"""Local-only demo server: python -m interaction_demo.app."""
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse
from interaction_demo.core import Campaign

ROOT = Path(__file__).parent
DB = Path(os.environ.get('CHIPCHECK_DEMO_DB', str(Path.home()/'.local/share/chipcheck/interaction-demo.sqlite3')))
DB.parent.mkdir(parents=True, exist_ok=True)

class Handler(BaseHTTPRequestHandler):
    def reply(self, code, payload, content='application/json'):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code); self.send_header('Content-Type', content); self.send_header('Content-Length', str(len(data))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/': return self.reply(200, (ROOT/'index.html').read_bytes(), 'text/html; charset=utf-8')
        if path.startswith('/api/campaign/'):
            try: return self.reply(200, Campaign(DB).state(path.rsplit('/',1)[-1]))
            except ValueError as e: return self.reply(400, {'error':str(e)})
        self.reply(404, {'error':'Not found'})
    def do_POST(self):
        try:
            if self.headers.get('Origin') not in (None, 'http://127.0.0.1:8765', 'http://localhost:8765'): raise ValueError('Invalid origin')
            size = int(self.headers.get('Content-Length','0'))
            if size > 10000: raise ValueError('Request too large')
            data = json.loads(self.rfile.read(size)); c = Campaign(DB)
            if self.path == '/api/create':
                cid = c.create(data['planner'], int(data['budget']), int(data['seed'])); result = c.state(cid)
            elif self.path == '/api/propose': result = c.propose(data['id'], int(data['count']), data.get('purpose','explore'))
            elif self.path == '/api/run': result = c.run_pending(data['id'])
            else: return self.reply(404, {'error':'Not found'})
            self.reply(200,result)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e: self.reply(400, {'error':str(e)})

if __name__ == '__main__':
    print('ChipCheck simulation: http://127.0.0.1:8765', flush=True)
    HTTPServer(('127.0.0.1',8765),Handler).serve_forever()
