"""Cloudflare Access JWT verification.

Tokens are signed with the 'cryptography' package, so the hand-rolled RS256
check in auth.py is tested against an independent implementation rather than
against itself. The JWKS fetch is monkeypatched; nothing here touches the
network.
"""
import asyncio
import base64
import json
import time
from email.message import Message
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import auth

TEAM = "https://md-labor.cloudflareaccess.com"
AUD = "test-policy-aud"
KID = "test-kid"


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def int_b64url(value):
    return b64url(value.to_bytes((value.bit_length() + 7) // 8, "big"))


def make_key(bits=2048):
    return rsa.generate_private_key(public_exponent=65537, key_size=bits)


def jwk_for(key, kid=KID):
    numbers = key.public_key().public_numbers()
    return {"kty": "RSA", "kid": kid, "alg": "RS256",
            "n": int_b64url(numbers.n), "e": int_b64url(numbers.e)}


KEY = make_key()


def sign(payload, key=KEY, kid=KID):
    header = {"alg": "RS256", "kid": kid, "typ": "JWT"}
    signing_input = (b64url(json.dumps(header).encode()) + "."
                     + b64url(json.dumps(payload).encode()))
    signature = key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    return signing_input + "." + b64url(signature)


def claims(**overrides):
    base = {"aud": [AUD], "email": "Jay.Huie@Maryland.gov",
            "exp": int(time.time()) + 600, "iss": TEAM}
    base.update(overrides)
    return base


class FakeFetchResponse:
    def __init__(self, body, status=200):
        self._body = body
        self.status = status
        self.ok = 200 <= status < 300

    async def json(self):
        return self._body


@pytest.fixture
def jwks(monkeypatch):
    """The JWKS the fake Access team serves. Tests may mutate it."""
    served = {"keys": [jwk_for(KEY)], "status": 200, "urls": []}

    async def fake_fetch(url, **kwargs):
        served["urls"].append(url)
        return FakeFetchResponse({"keys": served["keys"]}, served["status"])

    monkeypatch.setattr(auth, "fetch", fake_fetch)
    return served


def env(**overrides):
    values = {"CLOUDFLARE_TEAM_DOMAIN": TEAM, "CLOUDFLARE_POLICY_AUD": AUD}
    values.update(overrides)
    return SimpleNamespace(**{k: v for k, v in values.items() if v is not None})


def request_with(jwt=None):
    headers = Message()
    if jwt is not None:
        headers[auth.AUTH_HEADER] = jwt
    return SimpleNamespace(headers=headers)


def context(jwt, environment=None):
    return asyncio.run(auth.get_auth_context(request_with(jwt), environment or env()))


class TestAccepted:
    def test_a_valid_token_authenticates(self, jwks):
        ctx = context(sign(claims()))
        assert ctx.is_authenticated
        assert ctx.email == "jay.huie@maryland.gov"
        assert ctx.roles == ["user"]
        assert jwks["urls"] == [f"{TEAM}/cdn-cgi/access/certs"]

    def test_a_string_audience_is_accepted(self, jwks):
        assert context(sign(claims(aud=AUD))).is_authenticated

    def test_the_header_name_is_case_insensitive(self, jwks):
        headers = Message()
        headers["cf-access-jwt-assertion"] = sign(claims())
        ctx = asyncio.run(auth.get_auth_context(SimpleNamespace(headers=headers), env()))
        assert ctx.is_authenticated

    def test_the_right_key_is_picked_by_kid(self, jwks):
        other = make_key()
        jwks["keys"] = [jwk_for(other, kid="other"), jwk_for(KEY)]
        assert context(sign(claims())).is_authenticated

    def test_a_trailing_slash_on_the_team_domain_is_tolerated(self, jwks):
        assert context(sign(claims()), env(CLOUDFLARE_TEAM_DOMAIN=TEAM + "/")).is_authenticated
        assert jwks["urls"] == [f"{TEAM}/cdn-cgi/access/certs"]


class TestNotMaryland:
    def test_a_verified_outside_email_is_known_but_not_authenticated(self, jwks):
        ctx = context(sign(claims(email="someone@example.com")))
        assert ctx.email == "someone@example.com"
        assert not ctx.is_authenticated
        assert ctx.roles == []

    def test_a_lookalike_domain_is_refused(self, jwks):
        assert not context(sign(claims(email="x@notmaryland.gov"))).is_authenticated
        assert not context(sign(claims(email="x@maryland.gov.evil.com"))).is_authenticated


def assert_refused(ctx):
    assert ctx == auth.AuthContext()


class TestRefused:
    def test_no_header(self, jwks):
        assert_refused(context(None))
        assert jwks["urls"] == []

    def test_no_team_domain(self, jwks):
        assert_refused(context(sign(claims()), env(CLOUDFLARE_TEAM_DOMAIN=None)))

    @pytest.mark.parametrize("aud", [None, ""])
    def test_no_policy_aud_fails_closed(self, jwks, aud):
        assert_refused(context(sign(claims()), env(CLOUDFLARE_POLICY_AUD=aud)))
        assert jwks["urls"] == []

    @pytest.mark.parametrize("aud", ["other-app", ["other-app"], [], None])
    def test_audience_mismatch(self, jwks, aud):
        assert_refused(context(sign(claims(aud=aud))))

    def test_expired(self, jwks):
        assert_refused(context(sign(claims(exp=int(time.time()) - 1))))

    def test_signed_by_another_key(self, jwks):
        assert_refused(context(sign(claims(), key=make_key())))

    def test_tampered_payload(self, jwks):
        header, _, signature = sign(claims(email="x@example.com")).split(".")
        forged = b64url(json.dumps(claims()).encode())
        assert_refused(context(f"{header}.{forged}.{signature}"))

    def test_truncated_signature(self, jwks):
        assert_refused(context(sign(claims())[:-4]))

    def test_unknown_kid(self, jwks):
        assert_refused(context(sign(claims(), kid="nope")))

    def test_jwks_fetch_failure(self, jwks):
        jwks["status"] = 503
        assert_refused(context(sign(claims())))

    def test_a_key_below_2048_bits_is_refused(self, jwks):
        small = make_key(1024)
        jwks["keys"] = [jwk_for(small)]
        assert_refused(context(sign(claims(), key=small)))

    def test_a_non_rsa_key_is_refused(self, jwks):
        jwks["keys"] = [{**jwk_for(KEY), "kty": "EC"}]
        assert_refused(context(sign(claims())))

    @pytest.mark.parametrize("jwt", [
        "", "abc", "a.b", "a.b.c.d",
        "!!!.!!!.!!!",
        b64url(b"not json") + "." + b64url(b"{}") + ".sig",
        b64url(b"[]") + "." + b64url(b"[]") + ".sig",
    ])
    def test_malformed(self, jwks, jwt):
        assert_refused(context(jwt))
