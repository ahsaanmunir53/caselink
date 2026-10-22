"""Accounts: scrypt password hashes and short-lived signed tokens.

Roles, lowest first: viewer (reads), analyst (decides on cases and suggestions), supervisor (also
manages users and confirms referrals). In demo mode, demo accounts log in with one click; they only
ever see synthetic data.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.db.models import User

log = logging.getLogger(__name__)

ROLES = ("viewer", "analyst", "supervisor")
RANK = {r: i for i, r in enumerate(ROLES)}
DEMO_USERS = [
    ("ayesha.analyst@caselink.demo", "Ayesha (analyst)", "analyst"),
    ("bilal.analyst@caselink.demo", "Bilal (analyst)", "analyst"),
    ("sana.supervisor@caselink.demo", "Sana (supervisor)", "supervisor"),
    ("viewer@caselink.demo", "Guest (viewer)", "viewer"),
]
DEFAULT_SECRET = "dev-only-auth-secret-change-me"
_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_token(settings: Settings, email: str, role: str) -> str:
    payload = _b64(json.dumps({"sub": email, "role": role, "exp": int(time.time()) + settings.token_hours * 3600}).encode())
    sig = _b64(hmac.new(settings.auth_secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_token(settings: Settings, token: str) -> dict | None:
    if not token.isascii() or login_available(settings):
        return None
    try:
        payload, sig = token.split(".")
    except ValueError:
        return None
    expected = _b64(hmac.new(settings.auth_secret.encode(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if data.get("exp", 0) < time.time() or data.get("role") not in ROLES:
        return None
    return data


def login_available(settings: Settings) -> str | None:
    """None if logging in (and accepting tokens) is allowed, else the reason it is not.

    The default secret is public, so anyone could sign a token with it. It is accepted only
    for local development and tests: never in production, and never with a real database."""
    weak = settings.auth_secret == DEFAULT_SECRET or len(settings.auth_secret) < 16
    if weak and (settings.app_env == "production" or settings.uses_postgres):
        return "Set AUTH_SECRET to a long random string (16+ characters) to enable logins."
    return None


@dataclass
class Principal:
    email: str
    name: str
    role: str
    demo: bool = False

    def can(self, role: str) -> bool:
        return RANK.get(self.role, -1) >= RANK[role]


async def principal_from_request(request: Request, role: str = "viewer") -> Principal:
    settings: Settings = request.app.state.settings
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else ""
    problem = login_available(settings)
    if problem:
        raise HTTPException(503, problem)
    data = read_token(settings, token) if token else None
    if not data:
        raise HTTPException(401, "Log in first.")
    async with request.app.state.deps.sessionmaker() as session:
        user = (await session.execute(select(User).where(User.email == data["sub"]))).scalar_one_or_none()
    if not user or not user.active or (user.demo and not settings.demo_mode):
        raise HTTPException(401, "This account is not active.")
    principal = Principal(user.email, user.name, user.role, user.demo)
    if not principal.can(role):
        raise HTTPException(403, f"This needs the {role} role.")
    return principal


async def require_viewer(request: Request) -> Principal:
    return await principal_from_request(request, "viewer")


async def require_analyst(request: Request) -> Principal:
    return await principal_from_request(request, "analyst")


async def require_supervisor(request: Request) -> Principal:
    return await principal_from_request(request, "supervisor")


async def bootstrap_users(sessionmaker: async_sessionmaker, settings: Settings) -> list[str]:
    """Create the demo accounts (demo mode) and the first supervisor from ADMIN_EMAIL / ADMIN_PASSWORD."""
    created = []
    async with sessionmaker() as session:
        existing = set((await session.execute(select(User.email))).scalars().all())
        if settings.demo_mode:
            for email, name, role in DEMO_USERS:
                if email not in existing:
                    session.add(User(email=email, name=name, role=role, demo=True))
                    created.append(email)
        if settings.admin_email and settings.admin_password:
            email = settings.admin_email.lower().strip()
            if len(settings.admin_password) < 10:
                log.warning("ADMIN_PASSWORD must be at least 10 characters; no supervisor account was created.")
            elif email not in existing:
                session.add(User(email=email, name=email.split("@")[0], role="supervisor",
                                 password_hash=hash_password(settings.admin_password)))
                created.append(email)
        await session.commit()
    return created
