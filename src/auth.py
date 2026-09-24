"""Cloudflare Access JWT verification.

Public surface: await get_auth_context(request, env) -> AuthContext

Access puts a signed RS256 JWT in the Cf-Access-Jwt-Assertion header of every
request it lets through. This checks its expiry, pins its audience to this
app's Access policy, and verifies the signature against the team's published
keys. Only a verified @maryland.gov address counts as authenticated.

The signature check is plain Python (hashlib + integer arithmetic) rather than
a call out to the runtime's WebCrypto: it behaves identically under Pyodide and
under pytest, needs no JS object conversion, and adds no package to the bundle.
It verifies the way RFC 8017 8.2.2 prescribes - rebuild the padded digest the
signature must decrypt to, and compare the whole block - rather than parsing
the decrypted block, which is where PKCS#1 v1.5 verifiers historically break.
"""
import base64
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass, field

from workers import fetch

log = logging.getLogger("auth")

AUTH_HEADER = "Cf-Access-Jwt-Assertion"
ALLOWED_EMAIL_DOMAIN = "@maryland.gov"

# DER encoding of the DigestInfo header for SHA-256 (RFC 8017 9.2, note 1).
# The digest itself follows it inside the padded block.
SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")

# Cloudflare signs with 2048-bit keys. A smaller modulus in the JWKS would be
# forgeable, so it is refused rather than trusted.
MIN_RSA_BITS = 2048

# The team's public keys are cached per isolate, which lives across many
# requests, so most requests verify without a round trip. Access rotates its
# signing key every six weeks and keeps publishing the previous one for a week
# after, so an hour-old copy is always new enough for tokens already issued.
JWKS_TTL_SECONDS = 3600

# A kid missing from the cache usually means a rotation this isolate has not
# seen yet, so it forces a refetch - but no more often than this, so a stream of
# tokens with made-up kids cannot turn every request back into a round trip.
JWKS_MIN_REFRESH_SECONDS = 60

# certs URL -> (fetched_at, keys)
_jwks_cache = {}


@dataclass
class AuthContext:
    is_authenticated: bool = False
    email: str | None = None
    roles: list[str] = field(default_factory=list)


def _b64url_bytes(value):
    """Decode unpadded base64url. Raises ValueError on anything malformed."""
    padded = value + "=" * (-len(value) % 4)
    # validate=True: without it, stray characters are silently dropped.
    return base64.b64decode(padded, altchars=b"-_", validate=True)


def _b64url_json(value):
    return json.loads(_b64url_bytes(value).decode("utf-8"))


def _b64url_int(value):
    return int.from_bytes(_b64url_bytes(value), "big")


def _rs256_verify(jwk, signing_input, signature):
    """RSASSA-PKCS1-v1_5 with SHA-256, for a public key in JWK form."""
    if jwk.get("kty") != "RSA":
        return False
    n = _b64url_int(jwk["n"])
    e = _b64url_int(jwk["e"])
    if n.bit_length() < MIN_RSA_BITS:
        log.warning("[auth] JWKS key is only %d bits; refusing it", n.bit_length())
        return False

    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    s = int.from_bytes(signature, "big")
    if s >= n:
        return False
    decrypted = pow(s, e, n).to_bytes(k, "big")

    t = SHA256_DIGEST_INFO + hashlib.sha256(signing_input).digest()
    expected = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(decrypted, expected)


async def _fetch_jwks(certs_url):
    res = await fetch(certs_url)
    if not res.ok:
        log.warning("[auth] JWKS fetch failed (%s) from %s", res.status, certs_url)
        return None
    keys = (await res.json()).get("keys")
    if not isinstance(keys, list):
        log.warning("[auth] JWKS from %s has no key list", certs_url)
        return None
    return keys


def _find_key(keys, kid):
    return next((key for key in keys if key.get("kid") == kid), None)


async def _get_jwk(team_domain, kid):
    """The team's public key for this kid, from the cache when it can be."""
    certs_url = f"{team_domain.rstrip('/')}/cdn-cgi/access/certs"
    now = time.time()

    cached = _jwks_cache.get(certs_url)
    if cached is not None:
        fetched_at, keys = cached
        age = now - fetched_at
        jwk = _find_key(keys, kid)
        if age < JWKS_TTL_SECONDS and (jwk is not None or age < JWKS_MIN_REFRESH_SECONDS):
            if jwk is None:
                log.warning("[auth] JWT Key ID not found in JWKS")
            return jwk

    keys = await _fetch_jwks(certs_url)
    if keys is None:
        # A failed fetch leaves any older copy in place for the next request.
        return None
    _jwks_cache[certs_url] = (now, keys)

    jwk = _find_key(keys, kid)
    if jwk is None:
        log.warning("[auth] JWT Key ID not found in JWKS")
    return jwk


async def verify_cloudflare_jwt(jwt, env):
    """Return the JWT's payload if it is valid for this app, else None."""
    try:
        parts = jwt.split(".") if isinstance(jwt, str) else []
        if len(parts) != 3:
            return None
        header_b64, payload_b64, signature_b64 = parts

        try:
            header = _b64url_json(header_b64)
            payload = _b64url_json(payload_b64)
        except ValueError:
            # json.JSONDecodeError, UnicodeDecodeError and binascii.Error are
            # all ValueErrors.
            log.warning("[auth] Malformed JWT JSON payload ignored.")
            return None
        if not isinstance(header, dict) or not isinstance(payload, dict):
            log.warning("[auth] Malformed JWT JSON payload ignored.")
            return None

        exp = payload.get("exp")
        if exp and exp < int(time.time()):
            log.warning("[auth] JWT expired")
            return None

        # Audience pinning is mandatory. Missing/empty AUD config means the JWT
        # could be from any Access app in this team - fail closed instead of
        # silently accepting it.
        policy_aud = getattr(env, "CLOUDFLARE_POLICY_AUD", None)
        if not policy_aud:
            log.error("[auth] CLOUDFLARE_POLICY_AUD not configured - refusing to verify JWT")
            return None
        aud = payload.get("aud")
        aud_matches = policy_aud in aud if isinstance(aud, list) else aud == policy_aud
        if not aud_matches:
            log.warning("[auth] JWT audience mismatch")
            return None

        jwk = await _get_jwk(env.CLOUDFLARE_TEAM_DOMAIN, header.get("kid"))
        if jwk is None:
            return None

        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        if not _rs256_verify(jwk, signing_input, _b64url_bytes(signature_b64)):
            return None
        return payload
    except Exception:
        log.exception("[auth] JWT verification exception")
        return None


async def get_auth_context(request, env):
    auth = AuthContext()

    try:
        jwt = request.headers.get(AUTH_HEADER)
        if not jwt or not getattr(env, "CLOUDFLARE_TEAM_DOMAIN", None):
            return auth

        payload = await verify_cloudflare_jwt(jwt, env)
        email = payload.get("email") if payload else None
        if isinstance(email, str) and email:
            auth.email = email.lower()
            if auth.email.endswith(ALLOWED_EMAIL_DOMAIN):
                auth.is_authenticated = True
                auth.roles.append("user")
    except Exception:
        log.exception("[auth] Error parsing Cloudflare Access JWT")

    return auth
