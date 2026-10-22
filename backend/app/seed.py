"""Load the synthetic dataset, and reset the public demo."""

import logging

from sqlalchemy import delete, func, select

from app.data.synthetic import generate
from app.db.models import (
    Alert,
    AuditEntry,
    Case,
    Entity,
    Link,
    Mention,
    Note,
    RejectedPair,
    Report,
    Suggestion,
)
from app.intel import audit
from app.link import service

log = logging.getLogger(__name__)


async def seed_if_empty(deps) -> int:
    if not deps.settings.seed_synthetic_data:
        return 0
    async with deps.sessionmaker() as session:
        if (await session.execute(select(func.count()).select_from(Report))).scalar():
            return 0
        reports, _ = generate()
        ids = await service.store_reports(session, reports, "system:seed")
        await service.rebuild(session, deps.settings, "agent:linker")
        await session.commit()
    log.info("Loaded %d synthetic reports", len(ids))
    return len(ids)


async def reset_and_seed(deps) -> dict:
    async with deps.sessionmaker() as session:
        case_ids = (await session.execute(select(Case.id))).scalars().all()
        if deps.checkpointer is not None:
            for cid in case_ids:
                try:
                    await deps.checkpointer.adelete_thread(f"review-{cid}-0")
                except Exception as exc:  # a missing thread is fine
                    log.debug("could not delete review thread for %s: %s", cid, exc)
        for table in (Alert, Note, Suggestion, RejectedPair, Link, Mention, Report, Case, Entity, AuditEntry):
            await session.execute(delete(table))
        await session.commit()
    n = await seed_if_empty(deps)
    async with deps.sessionmaker() as session:
        await audit.record(session, "system:cron", "demo.reset", "system", "demo", {"reports": n})
        await session.commit()
    return {"reports": n}
