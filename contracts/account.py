"""
AccountReference — opaque identifier for a financial account.

Design decisions
~~~~~~~~~~~~~~~~
* The ``account_id`` is an **opaque string** — it may be a hash, a
  pseudonym, or a masked real identifier.  The contract does not
  prescribe its format; it only requires the field to be non-empty.
* ``institution`` is the name or BIC/IFSC of the holding institution.
  It is optional because synthetic or partially-redacted feeds may omit
  it.
* ``label`` is an optional human-friendly tag for display only.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AccountReference(BaseModel):
    """Minimal, opaque reference to a financial account."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
    )

    account_id: str = Field(
        ...,
        min_length=1,
        description="Opaque account identifier (hash, pseudonym, or masked ID).",
    )
    institution: str | None = Field(
        default=None,
        description="Holding institution name, BIC, or IFSC code.",
    )
    label: str | None = Field(
        default=None,
        description="Optional human-friendly display label.",
    )
