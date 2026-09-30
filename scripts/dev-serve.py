#!/usr/bin/env python3
"""Levanta auth(9002) + portal(9003) + admin-api(9004) + frontend(3001) en local."""
import os, sys, threading, time, subprocess, socket

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

os.environ.setdefault('JWT_RS256_PRIVATE_KEY_PATH', 'config/relay/certs/private.pem')
os.environ.setdefault('JWT_RS256_PUBLIC_KEY_PATH',  'config/relay/certs/public.pem')
os.environ.setdefault('REDIS_URL',       '')
os.environ.setdefault('CLICKHOUSE_URL',  'http://localhost:9999')
os.environ.setdefault('STRIPE_SECRET_KEY', 'sk_test_replace')

sys.path.insert(0, os.path.join(ROOT, 'comercial/auth'))
sys.path.insert(0, os.path.join(ROOT, 'comercial/portal'))
sys.path.insert(0, os.path.join(ROOT, 'admin/api'))

from auth_server   import app as auth_app
from portal_server import app as portal_app
from admin_server  import app as admin_app

import http.server, socketserver

class SilentCORSHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()
    def do_OPTIONS(self):
        self.send_response(200); self.end_headers()
    def log_message(self, *a): pass

def run_flask(app, port):
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

def run_static(directory, port):
    target = os.path.join(ROOT, directory)

    class Handler(SilentCORSHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=target, **kwargs)

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(('', port), Handler) as httpd:
        httpd.serve_forever()

threads = [
    threading.Thread(target=run_flask,  args=(auth_app,   9002), daemon=True),
    threading.Thread(target=run_flask,  args=(portal_app, 9003), daemon=True),
    threading.Thread(target=run_flask,  args=(admin_app,  9004), daemon=True),
    threading.Thread(target=run_static, args=('admin/src', 3001), daemon=True),
]
for t in threads: t.start()
time.sleep(2)

# Verificar
for name, port, path in [('auth', 9002, '/health'), ('portal', 9003, '/health'),
                           ('admin-api', 9004, '/health'), ('frontend', 3001, '/index.html')]:
    try:
        s = socket.create_connection(('localhost', port), timeout=2)
        s.close()
        print(f'  ✓ {name:12} http://localhost:{port}{path}')
    except Exception:
        print(f'  ✗ {name:12} no responde en {port}')

print()
print('Admin UI:    http://localhost:3001/index.html')
print('Auth API:    http://localhost:9002/health')
print('Admin API:   http://localhost:9004/health')
print()
print('Login: admin@teremoqwow.dev / dev-secret')
print()
print('Ctrl+C para parar')

try:
    while True: time.sleep(1)
except KeyboardInterrupt:
    print('\nParado.')
