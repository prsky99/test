"""Explicit local ChatGPT evaluation login; no project server is started."""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlsplit
import uuid

import httpx

from .workflow_chatgpt import AUTH, SCOPES, LoginAttempt, private_read, private_write
from .workspace_access import WorkspaceDenied


def login_attempt(root, redirect_uri, host, expected_email):
    """Reuse this local application's issued client without copying auth caches."""
    path = root / 'credentials.json'
    if not path.exists() and not path.is_symlink():
        return LoginAttempt(redirect_uri, host, expected_email=expected_email)
    record = private_read(path)
    if (record.get('profile') != 'workflow-chatgpt-local-v1'
            or record.get('issuer') != AUTH or record.get('ext_agent_host_id') != host
            or type(record.get('client_id')) is not str
            or not re.fullmatch(r'oaiapp_[A-Za-z0-9_-]{1,200}', record['client_id'])
            or type(record.get('subject')) is not str or not record['subject']
            or type(record.get('email')) is not str
            or record['email'].casefold() != expected_email.casefold()
            or type(record.get('scopes')) is not list
            or any(type(scope) is not str for scope in record['scopes'])
            or not set(SCOPES).issubset(record['scopes'])):
        raise WorkspaceDenied()
    return LoginAttempt(redirect_uri, host, client_id=record['client_id'],
                        expected_email=expected_email, expected_subject=record['subject'])


def callback_handler(root, pending, outcome):
    """Redirect completed callbacks to a page without one-use query credentials."""
    class Handler(BaseHTTPRequestHandler):
        server_version='Agent Concierge'
        sys_version=''

        def log_message(self,*args):pass

        def page(self, success, status=None):
            message=('ChatGPT connection verified. Return to Agent Concierge.' if success else
                     'The connection could not be verified. Return to Agent Concierge.')
            title='Connection verified' if success else 'Connection unavailable'
            body=('<!doctype html><html lang="en"><title>'+title+'</title><p>'+message+'</p></html>').encode()
            self.send_response(status if status is not None else (200 if success else 400))
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('X-Robots-Tag','noindex,noarchive')
            self.send_header('Content-Security-Policy',"default-src 'none'; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(body)

        def do_GET(self):
            try:target=urlsplit(self.path)
            except ValueError:self.page(False,400);return
            if target.path=='/auth/complete' and not target.query:
                outcome['shown']=pending().consumed
                self.page(outcome['complete']);return
            if target.path!='/auth/callback' or len(self.path)>8192:
                self.page(False,404);return
            query=parse_qs(target.query,keep_blank_values=True)
            if any(len(value)!=1 for value in query.values()):
                self.page(False,400);return
            try:
                with httpx.Client(trust_env=False,follow_redirects=False) as client:
                    record=pending().complete(client,{key:value[0] for key,value in query.items()})
                private_write(root/'credentials.json',record)
                outcome['complete']=True
            except Exception:
                outcome['callback_failed']=True
            self.send_response(303)
            self.send_header('Location','/auth/complete')
            self.send_header('Content-Length','0')
            self.send_header('Cache-Control','no-store')
            self.send_header('Referrer-Policy','no-referrer')
            self.end_headers()
    return Handler


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',required=True)
    parser.add_argument('--expected-email',required=True)
    args=parser.parse_args(); root=Path(args.directory).absolute()
    host_file=root/'host.json'
    if host_file.exists():host=private_read(host_file)['id']
    else:
        host='urn:uuid:'+str(uuid.uuid4());private_write(host_file,{'id':host})
    outcome={'complete':False,'shown':False}
    attempt=None
    server=HTTPServer(('127.0.0.1',0),callback_handler(root,lambda:attempt,outcome));server.timeout=1
    try:
        attempt=login_attempt(root,'http://127.0.0.1:'+str(server.server_port)+'/auth/callback',host,args.expected_email)
        private_write(root/'authorization.json',{'authorization_url':attempt.authorization_url()})
        print('Local authorization is ready. Complete the browser sign-in within five minutes.',flush=True)
        while time.time()-attempt.created<300 and not (attempt.consumed and outcome['shown']):
            server.handle_request()
    finally:
        server.server_close()
        (root/'authorization.json').unlink(missing_ok=True)
    print('Connection verified and stored privately.' if outcome['complete'] else 'Connection was not completed.',flush=True)


if __name__=='__main__':main()
