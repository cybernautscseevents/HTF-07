"""
FraudCase — an observed fraud investigation envelope.

Design decisions
~~~~~~~~~~~~~~~~
* A case groups zero or more ``transaction_ids`` under a single
  investigation umbrella.  A case may be opened from a customer
  report, bank detection signal, or shared intelligence *before*
  the relevant transaction events have been ingested.
* ``origin`` records how the case entered AEGIS-Flow.
* ``opened_at`` / ``updated_at`` are timezone-aware UTC datetimes.
* No derived fields (total taint, aggregate risk, intervention
  recommendation) are included.  Those are produced by downstream
  engines and attached separately.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from contracts.enums import CaseOrigin, CaseStatus

# ── Constants ────────────────────────────────────────────────────────────────

SCHEMA_VERSION = "1.0.0"


class FraudCase(BaseModel):
    """An observed fraud investigation case."""

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
    case_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier for this fraud case.",
    )
    title: str = Field(
        ...,
        min_length=1,
        description="Short human-readable title for the case.",
    )
    description: str | None = Field(
        default=None,
        description="Free-text description or notes.",
    )

    # ── Origin ───────────────────────────────────────────────────────────
    origin: CaseOrigin = Field(
        ...,
        description="How this fraud case entered AEGIS-Flow.",
    )

    # ── Status ───────────────────────────────────────────────────────────
    status: CaseStatus = Field(
        ...,
        description="Current lifecycle status of the case.",
    )

    # ── Linked transactions ──────────────────────────────────────────────
    transaction_ids: list[str] = Field(
        default_factory=list,
        description=(
            "IDs of transactions associated with this case. "
            "May be empty when a case is opened before transaction "
            "events are ingested."
        ),
    )

    # ── Time ─────────────────────────────────────────────────────────────
    opened_at: datetime = Field(
        ...,
        description="Timezone-aware datetime when the case was opened.",
    )
    updated_at: datetime = Field(
        ...,
        description="Timezone-aware datetime of last update.",
    )

    # ── Validators ───────────────────────────────────────────────────────

    @field_validator("opened_at", "updated_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware.")
        return v
