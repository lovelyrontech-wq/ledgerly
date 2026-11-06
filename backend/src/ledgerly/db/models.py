"""Ledgerly data model. See docs/architecture/ARCHITECTURE.md, section 4.

Works on SQLite (dev) and Postgres. Status/role values are enforced with CHECK constraints
so bad values are rejected by the database, not only by application code.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Stable constraint names, so Alembic migrations are the same on every database.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# JSON on SQLite, JSONB on Postgres.
JsonType = JSON().with_variant(JSONB(), "postgresql")

FOLDER_TYPES = ("invoice", "product")
SHARE_ROLES = ("editor", "viewer")
BATCH_STATUSES = ("pending", "applied", "undone", "expired", "cancelled")
BATCH_ITEM_RESULTS = ("applied", "skipped_changed", "failed", "undone", "undo_skipped")


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    owned_folders: Mapped[list[Folder]] = relationship(back_populates="owner")
    permissions: Mapped[list[FolderPermission]] = relationship(back_populates="user")


class Folder(Base):
    __tablename__ = "folders"
    __table_args__ = (CheckConstraint(_in("type", FOLDER_TYPES), name="type"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    owner: Mapped[User] = relationship(back_populates="owned_folders")
    permissions: Mapped[list[FolderPermission]] = relationship(back_populates="folder", cascade="all, delete-orphan")
    records: Mapped[list[LedgerRecord]] = relationship(back_populates="folder", cascade="all, delete-orphan")


class FolderPermission(Base):
    """Sharing. The owner has full access implicitly and is not listed here."""

    __tablename__ = "folder_permissions"
    __table_args__ = (CheckConstraint(_in("role", SHARE_ROLES), name="role"),)

    folder_id: Mapped[str] = mapped_column(ForeignKey("folders.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    folder: Mapped[Folder] = relationship(back_populates="permissions")
    user: Mapped[User] = relationship(back_populates="permissions")


class LedgerRecord(Base):
    """A record in a folder (an invoice or a product).

    Money is integer cents; never store money as a float. `version` increases on every
    write, and bulk apply only writes a record whose version still matches its preview.
    """

    __tablename__ = "records"
    __table_args__ = (
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("value_cents >= 0", name="value_non_negative"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    folder_id: Mapped[str] = mapped_column(ForeignKey("folders.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    value_cents: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20))
    # Type-specific fields: customer/issuedAt/dueAt for invoices, sku/stock/category for products.
    fields: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    folder: Mapped[Folder] = relationship(back_populates="records")


class Batch(Base):
    """One bulk change: created as a pending preview, then applied, undone, expired or cancelled."""

    __tablename__ = "batches"
    __table_args__ = (
        CheckConstraint(_in("status", BATCH_STATUSES), name="status"),
        Index("ix_batches_folder_id_status", "folder_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    folder_id: Mapped[str] = mapped_column(ForeignKey("folders.id", ondelete="CASCADE"))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # The user's request in their own words, e.g. "update the values in this folder by 10%".
    instruction: Mapped[str] = mapped_column(Text)
    # Set when applied. Repeating an apply with the same key returns the stored result.
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[BatchItem]] = relationship(back_populates="batch", cascade="all, delete-orphan")


class BatchItem(Base):
    """One record's change in a batch: exact record ID, old and new value, and the version it was previewed at."""

    __tablename__ = "batch_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "record_id", name="uq_batch_items_batch_id_record_id"),
        CheckConstraint(f"result IS NULL OR {_in('result', BATCH_ITEM_RESULTS)}", name="result"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"))
    record_id: Mapped[str] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(50), default="value_cents")
    before: Mapped[int] = mapped_column(BigInteger)
    after: Mapped[int] = mapped_column(BigInteger)
    expected_version: Mapped[int] = mapped_column(Integer)
    # None while pending.
    result: Mapped[str | None] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text)

    batch: Mapped[Batch] = relationship(back_populates="items")
    record: Mapped[LedgerRecord] = relationship()


class AuditLog(Base):
    """Append-only. The app never updates or deletes rows here."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_user_id_at", "user_id", "at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    # e.g. "batch.preview", "batch.apply", "batch.undo", "record.update"
    action: Mapped[str] = mapped_column(String(50))
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("batches.id"), index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
