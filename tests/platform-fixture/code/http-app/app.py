from http.server import BaseHTTPRequestHandler, HTTPServer
import hashlib
import json
import os

VERSION = 'fixture-v1'
RETRY_ATTEMPTS = 0


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        global RETRY_ATTEMPTS
        if self.path=='/retry':
            RETRY_ATTEMPTS+=1
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'attempt':RETRY_ATTEMPTS}).encode())
            return
        if self.path not in ['/ready', '/data']:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'version':VERSION,'message':os.getenv('MESSAGE'),
                                    'secret_present':bool(os.getenv('PASSWORD')),
                                    'secret_digest':hashlib.sha256(os.getenv('PASSWORD','').encode()).hexdigest()}).encode())


if __name__ == '__main__':
    HTTPServer(('0.0.0.0',8123),Handler).serve_forever()
