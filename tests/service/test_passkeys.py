"""Passkey sign-in, exercised with a software authenticator that signs real WebAuthn responses."""

import datetime as dt
import hashlib
import json
import secrets

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from pydantic import ValidationError
from webauthn.helpers import bytes_to_base64url as b64

from stocks_service.api.app import create_app
from stocks_service.settings import Settings
from stocks_service.web import passkeys

ORIGIN = "https://stocks.example.test"
TOKEN = "t" * 40


class Authenticator:
    """A minimal ES256 platform authenticator (user present, optionally verified, backed up)."""

    def __init__(self, origin=ORIGIN):
        self.origin, self.rp = origin, origin.split("://")[1].split(":")[0]
        self.key, self.id = ec.generate_private_key(ec.SECP256R1()), secrets.token_bytes(20)

    def _client_data(self, kind, challenge):
        return json.dumps({"type": kind, "challenge": challenge, "origin": self.origin, "crossOrigin": False}).encode()

    def _auth_data(self, *, verified, attested=b"", count=0):
        flags = 0x01 | (0x04 if verified else 0) | 0x08 | 0x10 | (0x40 if attested else 0)
        return hashlib.sha256(self.rp.encode()).digest() + bytes([flags]) + count.to_bytes(4, "big") + attested

    def create(self, challenge, *, verified=True):
        n = self.key.public_key().public_numbers()
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})
        attested = bytes(16) + len(self.id).to_bytes(2, "big") + self.id + cose
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": self._auth_data(verified=verified, attested=attested)})
        return {"id": b64(self.id), "rawId": b64(self.id), "type": "public-key", "clientExtensionResults": {},
                "response": {"clientDataJSON": b64(self._client_data("webauthn.create", challenge)),
                             "attestationObject": b64(att)}}

    def get(self, challenge, *, verified=True, key=None):
        client = self._client_data("webauthn.get", challenge)
        auth = self._auth_data(verified=verified)
        sig = (key or self.key).sign(auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64(self.id), "rawId": b64(self.id), "type": "public-key", "clientExtensionResults": {},
                "response": {"clientDataJSON": b64(client), "authenticatorData": b64(auth), "signature": b64(sig),
                             "userHandle": b64(passkeys.USER_ID)}}


def _client(db, **kw):
    s = Settings(**{"mongo_url": "mongodb://unused", "api_keys": "k", "login_token": TOKEN,
                    "session_secret": "s" * 40, "public_url": ORIGIN, **kw})
    return TestClient(create_app(s, db=db), base_url=ORIGIN)


def _link(c):
    assert c.post("/login/link", data={"token": TOKEN}, follow_redirects=False).status_code == 303


def _add(c, a, name="iCloud Keychain", **kw):
    o = c.post("/security/passkeys/options").json()
    return c.post("/security/passkeys", json={"credential": a.create(o["challenge"], **kw), "name": name})


def _options(c):
    return c.post("/login/passkey/options").json()


def _signed_in(c):
    return c.get("/security", follow_redirects=False).status_code == 200


@pytest.fixture
def site(db):
    """A client with one passkey added, signed out."""
    with _client(db) as c:
        a = Authenticator()
        _link(c)
        assert _add(c, a).status_code == 200
        c.post("/logout")
        yield c, a


def test_add_a_passkey_then_sign_in_with_it(db):
    with _client(db) as c:
        assert 'id="passkey-signin"' not in c.get("/login").text      # none yet: only the sign-in link is offered
        a = Authenticator()
        _link(c)
        assert "No passkeys yet" in c.get("/security").text
        o = c.post("/security/passkeys/options").json()
        assert o["rp"]["id"] == "stocks.example.test"
        assert o["authenticatorSelection"]["userVerification"] == "required"
        assert o["authenticatorSelection"]["residentKey"] == "required"
        r = c.post("/security/passkeys", json={"credential": a.create(o["challenge"]), "name": " My  iPhone "})
        assert r.status_code == 200
        assert "My iPhone" in c.get("/security").text
        assert [x["id"] for x in c.post("/security/passkeys/options").json()["excludeCredentials"]] == [b64(a.id)]
        c.post("/logout")
        assert not _signed_in(c)
        page = c.get("/login").text
        assert 'id="passkey-signin"' in page and "/static/passkey.js" in page
        o = _options(c)
        assert o["userVerification"] == "required" and not o.get("allowCredentials")   # discloses no credential
        r = c.post("/login/passkey", json={"credential": a.get(o["challenge"])})
        assert r.status_code == 200 and "max-age=7776000" in r.headers["set-cookie"].lower()
        assert _signed_in(c)
        assert "this session" in c.get("/security").text
    doc = db.passkeys.find_one()
    assert doc["last_used_at"] is not None and doc["synced"] is True
    assert set(doc) == {"_id", "name", "public_key", "sign_count", "synced", "rp_id", "created_at", "last_used_at"}


def test_only_a_signed_in_owner_can_add_or_remove_passkeys(site, db):
    c, a = site
    for path in ("/security/passkeys/options", "/security/passkeys", f"/security/passkeys/{b64(a.id)}/delete"):
        r = c.post(path, json={"credential": {}, "name": "x"}, follow_redirects=False)
        assert (r.status_code, r.headers["location"]) == (303, "/login")
    assert db.passkeys.count_documents({}) == 1


@pytest.mark.parametrize("case", ["unknown", "wrong_key", "wrong_origin", "unverified", "wrong_challenge",
                                  "no_challenge", "malformed", "expired", "register_challenge"])
def test_bad_sign_ins_are_refused(site, db, case, monkeypatch):
    c, a = site
    challenge = None if case == "no_challenge" else _options(c)["challenge"]
    cred = a.get(challenge or b64(b"x" * 32))
    if case == "unknown":
        other = Authenticator()
        cred = other.get(challenge)
    elif case == "wrong_key":
        cred = a.get(challenge, key=ec.generate_private_key(ec.SECP256R1()))
    elif case == "wrong_origin":
        a.origin = "https://evil.example.test"
        cred = a.get(challenge)
    elif case == "unverified":
        cred = a.get(challenge, verified=False)
    elif case == "wrong_challenge":
        cred = a.get(b64(b"y" * 32))
    elif case == "malformed":
        cred = {"id": b64(a.id), "response": {"clientDataJSON": 3}}
    elif case == "expired":
        real = passkeys.time.time()
        monkeypatch.setattr(passkeys.time, "time", lambda: real + passkeys.CHALLENGE_SECONDS + 5)
    elif case == "register_challenge":
        _link(c)
        cred = a.get(c.post("/security/passkeys/options").json()["challenge"])
    r = c.post("/login/passkey", json={"credential": cred})
    assert r.status_code == 401 and r.json()["detail"]
    if case != "register_challenge":   # (that session was already signed in with the link)
        monkeypatch.undo()
        assert not _signed_in(c)
    assert db.passkeys.find_one()["last_used_at"] is None
    assert db.passkey_used_challenges.count_documents({"_id": challenge}) == 0    # nothing written for a failure


def test_a_captured_response_cannot_be_replayed(site):
    c, a = site
    o = _options(c)
    cookie = c.cookies.get("session")
    cred = a.get(o["challenge"])
    assert c.post("/login/passkey", json={"credential": cred}).status_code == 200
    c.cookies.clear()
    c.cookies.set("session", cookie)
    r = c.post("/login/passkey", json={"credential": cred})
    assert r.status_code == 401 and "already used" in r.json()["detail"]


def test_a_failed_attempt_spends_the_challenge_in_the_session(site):
    c, a = site
    o = _options(c)
    assert c.post("/login/passkey", json={"credential": a.get(b64(b"z" * 32))}).status_code == 401
    assert c.post("/login/passkey", json={"credential": a.get(o["challenge"])}).status_code == 401


def test_removing_a_passkey_ends_its_sessions(site, db):
    c, a = site
    assert c.post("/login/passkey", json={"credential": a.get(_options(c)["challenge"])}).status_code == 200
    with _client(db) as other:
        _link(other)
        r = other.post(f"/security/passkeys/{b64(a.id)}/delete", follow_redirects=False)
        assert (r.status_code, r.headers["location"]) == (303, "/security?removed=1")
        assert other.post(f"/security/passkeys/{b64(a.id)}/delete").status_code == 404
        assert _signed_in(other)                      # link sessions do not depend on a passkey
    assert not _signed_in(c)
    assert c.post("/login/passkey", json={"credential": a.get(_options(c)["challenge"])}).status_code == 401


def test_registration_refusals(db):
    with _client(db) as c:
        _link(c)
        a = Authenticator()
        assert _add(c, a, verified=False).status_code == 400          # needs Face ID / PIN
        assert _add(c, a, name="   ").status_code == 400
        assert _add(c, a, name="x" * 61).status_code == 400
        assert _add(c, Authenticator("https://evil.example.test")).status_code == 400
        assert db.passkeys.count_documents({}) == 0
        assert _add(c, a).status_code == 200
        r = _add(c, a)
        assert r.status_code == 400 and "already added" in r.json()["detail"]


def test_passkeys_need_a_configured_address(db):
    with _client(db, public_url="") as c:
        assert c.post("/login/passkey/options").status_code == 503
        _link(c)
        assert "Passkeys are not configured" in c.get("/security").text
        assert c.post("/security/passkeys/options").status_code == 503


def test_address_comes_from_the_setting_or_railways_domain():
    def s(**kw):
        return Settings(mongo_url="x", **kw)
    assert s(public_url="https://A.example/").passkey_origin() == "https://a.example"
    assert s(public_url="http://localhost:8000").passkey_origin() == "http://localhost:8000"
    assert s(RAILWAY_PUBLIC_DOMAIN="x.up.railway.app").passkey_origin() == "https://x.up.railway.app"
    assert s(public_url="https://a.example", RAILWAY_PUBLIC_DOMAIN="x.up.railway.app").passkey_origin() == "https://a.example"
    for bad in ("http://a.example", "https://a.example/path", "a.example", "https://u@a.example"):
        with pytest.raises(ValidationError, match="STOCKS_PUBLIC_URL"):
            s(public_url=bad)


def test_passkeys_give_no_access_to_mcp_or_the_api(site):
    c, a = site
    assert c.post("/login/passkey", json={"credential": a.get(_options(c)["challenge"])}).status_code == 200
    assert c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 401
    assert c.get("/api/v1/symbols").status_code == 401


def test_site_is_closed_to_robots_and_anonymous_visitors(db):
    with _client(db) as c:
        assert c.get("/robots.txt").text == "User-agent: *\nDisallow: /\n"
        for path in ("/docs", "/openapi.json", "/security", "/"):
            r = c.get(path, follow_redirects=False)
            assert (r.status_code, r.headers["location"]) == (303, "/login"), path
            assert "noindex" in r.headers["x-robots-tag"]
        assert c.get("/redoc").status_code == 404
        _link(c)
        assert "/openapi.json" in c.get("/docs").text
        assert "/api/v1/symbols" in c.get("/openapi.json").json()["paths"]


def test_every_page_and_endpoint_requires_authentication(db):
    """A new route must be protected, or listed here deliberately."""
    public = {"/health", "/login", "/login/link", "/login/passkey", "/login/passkey/options", "/logout", "/robots.txt"}
    with _client(db) as c:
        checked = 0
        for route in c.app.routes:
            if not getattr(route, "methods", None) or route.path in public:
                continue
            path = route.path.replace("{", "").replace("}", "")
            for method in route.methods - {"HEAD", "OPTIONS"}:
                r = c.request(method, path, follow_redirects=False)
                assert r.status_code == 401 or (r.status_code, r.headers.get("location")) == (303, "/login"), (method, path, r.status_code)
                checked += 1
        assert checked > 30
