"""
EvidenceEnvelope — a container for a piece of evidence attached to a case.

Design decisions
~~~~~~~~~~~~~~~~
* ``provider_type`` classifies the system that produced the evidence
  (ingestion, graph engine, taint engine, ML model, human analyst, etc.).
* ``body`` is an opaque ``dict`` — its internal structure depends on
  the provider.  The contract does not validate body contents; that is
  the responsibility of each provider's own sub-schema.
* ``created_at`` is a timezone-aware UTC datetime.
* ``schema_version`` is included because evidence envelopes are
  externally serialized and may be stored long-term.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from contracts.enums import EvidenceProviderType

# ── Constants ────────────────────────────────────────────────────────────────

SCHEMA_VERSION = "1.0.0"


class EvidenceEnvelope(BaseModel):
    """A single piece of evidence linked to a fraud case."""

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
    evidence_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier for this evidence artifact.",
    )
    case_id: str = Field(
        ...,
        min_length=1,
        description="ID of the fraud case this evidence belongs to.",
    )

    # ── Provider ─────────────────────────────────────────────────────────
    provider_type: EvidenceProviderType = Field(
        ...,
        description="Category of the system that produced this evidence.",
    )
    provider_name: str = Field(
        ...,
        min_length=1,
        description="Concrete name of the provider (e.g. 'taint-engine-v2').",
    )

    # ── Payload ──────────────────────────────────────────────────────────
    summary: str = Field(
        ...,
        min_length=1,
        description="Human-readable summary of the evidence.",
    )
    body: dict[str, Any] = Field(
        ...,
        description=(
            "Opaque evidence payload. Internal structure is defined "
            "by the producing provider."
        ),
    )

    # ── Time ─────────────────────────────────────────────────────────────
    created_at: datetime = Field(
        ...,
        description="Timezone-aware datetime when the evidence was created.",
    )

    # ── Validators ───────────────────────────────────────────────────────

    @field_validator("created_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware.")
        return v
