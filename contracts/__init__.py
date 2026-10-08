"""
AEGIS-Flow — Canonical Financial Event Contract
================================================

Single source-of-truth data models that every AEGIS-Flow component
(ingestion, graph engine, taint propagation, ML, API, frontend)
consumes and produces.

These models capture **observed facts only**.  Computed/derived fields
(taint scores, risk scores, ML predictions, intervention rankings) are
intentionally excluded and will be produced by downstream services.

All financial amounts are represented as **integer minor units** (paise
for INR) to avoid floating-point rounding.

All timestamps are **timezone-aware** and serialized in **UTC ISO-8601**.
"""

from contracts.enums import (
    CaseOrigin,
    CaseStatus,
    EvidenceProviderType,
    EventOrigin,
    TransactionChannel,
    TransactionStatus,
)
from contracts.account import AccountReference
from contracts.transaction import TransactionEvent
from contracts.case import FraudCase
from contracts.evidence import EvidenceEnvelope

__all__ = [
    # Enums
    "CaseOrigin",
    "CaseStatus",
    "EvidenceProviderType",
    "EventOrigin",
    "TransactionChannel",
    "TransactionStatus",
    # Models
    "AccountReference",
    "TransactionEvent",
    "FraudCase",
    "EvidenceEnvelope",
]
