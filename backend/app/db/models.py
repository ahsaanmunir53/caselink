"""Database tables.

* reports        incoming fraud reports (synthetic in the demo); the source text and its translation
* entities       normalised identifiers (phone, IBAN, website, email, licence, handle, agency name)
* mentions       which report mentions which identifier, and who found it (rules, AI, name list)
* cases          groups of reports the linker proposed and people reviewed
* links          why two reports are connected (shared IBAN, same agency name, similar wording)
* suggestions    weaker connections waiting for a person: attach a report, merge two cases
* rejected_pairs report pairs a person said are NOT connected; never proposed again
* notes          analyst notes on a case
* alerts         watchlist hits, emerging patterns, new reports joining a case
* audit_log      every action by an agent or a person, hash-chained so edits are detectable
* users          viewers, analysts and supervisors
"""

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    source: Mapped[str] = mapped_column(String(24))  # hoshiyar | pardes_guard | police_desk | upload
    channel: Mapped[str] = mapped_column(String(24), default="web_form")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    language: Mapped[str] = mapped_column(String(8), default="en")
    reporter_city: Mapped[str | None] = mapped_column(String(64), nullable=True)
    destination_country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount_lost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="PKR")
    kind: Mapped[str] = mapped_column(String(24), default="other", index=True)
    text: Mapped[str] = mapped_column(Text)
    translation: Mapped[str | None] = mapped_column(Text, nullable=True)
    translation_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_extraction: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"), nullable=True, index=True)
    # True when a person put the report in its case (accepted a suggestion, approved the case).
    # The linker never moves a pinned report.
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("kind", "value", name="uq_entity_kind_value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    value: Mapped[str] = mapped_column(String(255))
    display: Mapped[str] = mapped_column(String(255))
    official: Mapped[bool] = mapped_column(Boolean, default=False)
    watched: Mapped[bool] = mapped_column(Boolean, default=False)
    watch_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    valid: Mapped[bool] = mapped_column(Boolean, default=True)


class Mention(Base):
    __tablename__ = "mentions"
    __table_args__ = (UniqueConstraint("report_id", "entity_id", name="uq_mention"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), index=True)
    raw: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="contact")
    source: Mapped[str] = mapped_column(String(16), default="rules")  # rules | ai | name_list


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="proposed", index=True)
    kind: Mapped[str] = mapped_column(String(24), default="other")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assignee: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    merged_into: Mapped[str | None] = mapped_column(String(16), nullable=True)
    tlp: Mapped[str] = mapped_column(String(16), default="TLP:AMBER")


class Link(Base):
    __tablename__ = "links"
    __table_args__ = (Index("ix_link_pair", "report_a", "report_b"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_a: Mapped[str] = mapped_column(String(16), index=True)
    report_b: Mapped[str] = mapped_column(String(16), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # identifier | name | abbreviation | similar
    strength: Mapped[str] = mapped_column(String(8))  # strong | weak
    detail: Mapped[str] = mapped_column(String(255))
    score: Mapped[float] = mapped_column(Float, default=1.0)


class Suggestion(Base):
    __tablename__ = "suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16))  # attach | merge | new_case
    case_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    other_case_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    report_ids: Mapped[list] = mapped_column(JSON, default=list)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    ai_verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)  # same | different | unsure
    ai_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RejectedPair(Base):
    __tablename__ = "rejected_pairs"
    __table_args__ = (UniqueConstraint("report_a", "report_b", name="uq_rejected_pair"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_a: Mapped[str] = mapped_column(String(16))
    report_b: Mapped[str] = mapped_column(String(16))
    decided_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    author: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(24))  # watchlist | emerging | joined_case | duplicate
    message: Mapped[str] = mapped_column(Text)
    case_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    report_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    seen: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class AuditEntry(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    actor: Mapped[str] = mapped_column(String(255))  # agent:linker, agent:writer, analyst:email
    action: Mapped[str] = mapped_column(String(48))
    object_type: Mapped[str] = mapped_column(String(24))
    object_id: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(16), default="analyst")  # viewer | analyst | supervisor
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
