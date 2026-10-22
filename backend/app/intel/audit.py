"""Tamper-evident audit log.

Every action by an agent or a person is one row. Each row stores the SHA-256 of its own content
together with the previous row's hash, so changing or deleting any past row breaks the chain from
that point on, and verify() says where. (It does not stop someone with database access from
rewriting the whole chain; for that, the latest hash can be published or sent elsewhere daily.)
"""

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditEntry

GENESIS = "0" * 64


def _digest(prev: str, ts: datetime, actor: str, action: str, object_type: str, object_id: str, details: dict) -> str:
    body = json.dumps({"prev": prev, "ts": ts.astimezone(UTC).isoformat(timespec="microseconds"), "actor": actor,
                       "action": action, "type": object_type, "id": object_id, "details": details},
                      sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


async def record(session: AsyncSession, actor: str, action: str, object_type: str, object_id: str,
                 details: dict | None = None) -> AuditEntry:
    """Add one entry. The caller commits."""
    await session.flush()
    last = (await session.execute(select(AuditEntry).order_by(AuditEntry.id.desc()).limit(1))).scalar_one_or_none()
    prev = last.hash if last else GENESIS
    ts = datetime.now(UTC)
    details = json.loads(json.dumps(details or {}, default=str))
    entry = AuditEntry(ts=ts, actor=actor, action=action, object_type=object_type, object_id=str(object_id),
                       details=details, prev_hash=prev,
                       hash=_digest(prev, ts, actor, action, object_type, str(object_id), details))
    session.add(entry)
    await session.flush()
    return entry


async def verify(session: AsyncSession) -> dict:
    """Walk the chain. Returns ok, the number of entries, and the first broken entry if any."""
    rows = (await session.execute(select(AuditEntry).order_by(AuditEntry.id))).scalars().all()
    prev = GENESIS
    for row in rows:
        ts = row.ts if row.ts.tzinfo else row.ts.replace(tzinfo=UTC)
        expected = _digest(prev, ts, row.actor, row.action, row.object_type, row.object_id, row.details or {})
        if row.prev_hash != prev or row.hash != expected:
            return {"ok": False, "entries": len(rows), "broken_at": row.id,
                    "detail": "This entry or the one before it was changed after it was written."}
        prev = row.hash
    return {"ok": True, "entries": len(rows), "head": prev}
