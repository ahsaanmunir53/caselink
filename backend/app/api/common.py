"""Shared helpers for the API: who may read, rate limits, and turning rows into JSON."""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.auth import Principal, principal_from_request
from app.db.models import Case, Report


class RateLimiter:
    """Small in-memory sliding window per client. Protects free AI quotas."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str, limit: int | None = None) -> None:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= (limit or self.per_minute):
            raise HTTPException(429, "Too many requests in a minute. Wait a moment and try again.")
        q.append(now)
        if len(self.hits) > 5000:
            for k in [k for k, v in self.hits.items() if not v or now - v[-1] > 60]:
                del self.hits[k]


def client_ip(request: Request) -> str:
    settings = request.app.state.settings
    hops = settings.trusted_proxy_hops
    if hops and settings.client_ip_header:
        value = request.headers.get(settings.client_ip_header, "").strip()
        if value:
            return value
    forwarded = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    if hops and len(forwarded) >= hops:
        return forwarded[-hops]
    return request.client.host if request.client else "unknown"


def limit(request: Request, bucket: str = "", per_minute: int | None = None) -> None:
    request.app.state.limiter.check(f"{client_ip(request)}:{bucket}", per_minute)


async def reader(request: Request) -> Principal | None:
    """In demo mode anyone may read (the data is synthetic). Otherwise reading needs a login."""
    settings = request.app.state.settings
    if settings.demo_mode and not request.headers.get("authorization"):
        limit(request, "read", settings.rate_limit_per_minute * 2)
        return None
    return await principal_from_request(request, "viewer")


def report_json(r: Report, full: bool = True) -> dict:
    out = {"id": r.id, "source": r.source, "channel": r.channel, "received_at": r.received_at.isoformat(),
           "language": r.language, "city": r.reporter_city, "destination": r.destination_country, "amount": r.amount_lost,
           "currency": r.currency, "kind": r.kind, "case_id": r.case_id, "pinned": r.pinned, "synthetic": r.synthetic,
           "duplicate_of": r.duplicate_of}
    if full:
        out.update(text=r.text, translation=r.translation, translation_model=r.translation_model, ai_extraction=r.ai_extraction)
    else:
        out["text"] = r.text[:220]
    return out


def case_json(c: Case, counts: dict | None = None) -> dict:
    out = {"id": c.id, "title": c.title, "status": c.status, "kind": c.kind, "priority": c.priority,
           "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat(),
           "approved_by": c.approved_by, "approved_at": c.approved_at.isoformat() if c.approved_at else None,
           "confirmed_by": c.confirmed_by, "confirmed_at": c.confirmed_at.isoformat() if c.confirmed_at else None,
           "assignee": c.assignee, "tlp": c.tlp, "merged_into": c.merged_into}
    if counts:
        out.update(counts)
    return out
