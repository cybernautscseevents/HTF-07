"""
TransactionEvent — the atomic observed financial movement.

Design decisions
~~~~~~~~~~~~~~~~
* **event_id** is the unique, immutable observation identity.
  **transaction_id** is the stable business/payment identity.
  Multiple lifecycle events (e.g. pending → completed → reversed) may
  share the same ``transaction_id`` while having distinct ``event_id``
  values.
* **amount_minor_units** is a non-negative ``int`` in the currency's
  minor unit (paise for INR in schema v1.0.0).  Using integers avoids
  all IEEE-754 rounding issues for money.
* **currency** is a 3-letter ISO-4217 code, upper-cased.  For schema
  version 1.0.0, INR (paise) is the primary/validated currency.
  Multi-currency support with explicit currency-exponent metadata may
  be added in a future schema version.
* **occurred_at** is when the financial event actually happened.
  **observed_at** is when the event was received/observed by AEGIS-Flow.
  Both must be timezone-aware.  Canonical serialization uses UTC.
* No computed fields (taint, risk score, ML prediction) are present.
  Those will be attached by downstream services.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator

from contracts.account import AccountReference
from contracts.enums import (
    EventOrigin,
    TransactionChannel,
    TransactionStatus,
)

# ── Constants ────────────────────────────────────────────────────────────────

SCHEMA_VERSION = "1.0.0"


class TransactionEvent(BaseModel):
    """A single observed financial transaction."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
    )

    # ── Identity ─────────────────────────────────────────────────────────
    schema_version: str = Field(
        default=SCHEMA_VERSION,
        description="Semantic version of this schema.",
    )
    event_id: str = Field(
        ...,
        min_length=1,
        description=(
            "Unique immutable observation/event identity. "
            "Each ingested observation gets its own event_id."
        ),
    )
    transaction_id: str = Field(
        ...,
        min_length=1,
        description=(
            "Stable business/payment identity. Multiple events "
            "(lifecycle observations) may share the same transaction_id."
        ),
    )
    reference: str | None = Field(
        default=None,
        description="External transaction reference (UTR, RRN, etc.).",
    )

    # ── Parties ──────────────────────────────────────────────────────────
    sender: AccountReference = Field(
        ...,
        description="Account that initiated the transfer.",
    )
    receiver: AccountReference = Field(
        ...,
        description="Account that received the transfer.",
    )

    # ── Money ────────────────────────────────────────────────────────────
    amount_minor_units: int = Field(
        ...,
        ge=0,
        description=(
            "Transaction amount in the currency's smallest unit "
            "(paise for INR). Must be >= 0."
        ),
    )
    currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description=(
            "ISO-4217 currency code (upper-case, e.g. 'INR'). "
            "Schema v1.0.0 primarily validates INR (paise)."
        ),
    )

    # ── Time ─────────────────────────────────────────────────────────────
    occurred_at: datetime = Field(
        ...,
        description="Timezone-aware moment the financial event actually happened.",
    )
    observed_at: datetime = Field(
        ...,
        description="Timezone-aware moment the event was received/observed by AEGIS-Flow.",
    )

    # ── Classification ───────────────────────────────────────────────────
    status: TransactionStatus = Field(
        ...,
        description="Observed lifecycle status of the transaction.",
    )
    channel: TransactionChannel = Field(
        ...,
        description="Channel or rail used for the transaction.",
    )
    origin: EventOrigin = Field(
        ...,
        description="How this event entered AEGIS-Flow.",
    )

    # ── Validators ───────────────────────────────────────────────────────

    @field_validator("currency")
    @classmethod
    def _currency_upper(cls, v: str) -> str:
        if v != v.upper():
            raise ValueError("Currency code must be upper-case ISO-4217.")
        return v

    @field_validator("occurred_at", "observed_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware.")
        return v
