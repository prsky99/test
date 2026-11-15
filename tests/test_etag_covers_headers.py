"""A computed ETag changes when a header that changes rendering changes (11-15, PM 11:3x).

On 11-15 /advertise and /methodology got their own CSP so their stylesheets load, but the body was the same: the origin
answered the edge's revalidation with 304 and the edge kept serving the old CSP that blocked the stylesheets until the
cache was purged by hand. The tag the contract computes now covers content-type, CSP, cache-control and Vary."""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from agent_market.concierge.public_http_contract import PublicHTTPContract

BODY = '<!doctype html><title>x</title><link rel="stylesheet" href="/new/en/assets/styles.css">'


def app_with(csp):
    app = FastAPI()

    @app.get('/advertise')
    def page():
        return HTMLResponse(BODY, headers={'Content-Security-Policy': csp} if csp else None)

    @app.get('/methodology')
    def tagged():
        return HTMLResponse(BODY, headers={'ETag': '"route-tag"'})

    return TestClient(PublicHTTPContract(app))


def test_same_body_new_csp_gets_a_new_tag_and_no_304():
    old = app_with(None).get('/advertise', headers={'accept': 'text/html'})
    new_client = app_with("style-src 'self' 'unsafe-inline'")
    new = new_client.get('/advertise', headers={'accept': 'text/html'})
    assert old.headers['etag'] != new.headers['etag']
    again = new_client.get('/advertise', headers={'accept': 'text/html', 'if-none-match': old.headers['etag']})
    assert again.status_code == 200 and "'self'" in again.headers['content-security-policy']
    same = new_client.get('/advertise', headers={'accept': 'text/html', 'if-none-match': new.headers['etag']})
    assert same.status_code == 304


def test_a_tag_the_route_set_is_kept():
    r = app_with(None).get('/methodology', headers={'accept': 'text/html'})
    assert r.headers['etag'] == 'W/"route-tag"'
