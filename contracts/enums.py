"""
Controlled-vocabulary enumerations for the canonical event contract.

Every enum uses ``str`` as a mixin so that Pydantic serializes values as
plain JSON strings (e.g. ``"completed"`` rather than ``1``).
"""

from enum import unique, StrEnum


# ── Transaction lifecycle ────────────────────────────────────────────────────


@unique
class TransactionStatus(StrEnum):
    """Observable status of a single transaction."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REVERSED = "reversed"
    HELD = "held"


# ── Channel through which the transaction was initiated ──────────────────────


@unique
class TransactionChannel(StrEnum):
    """Channel or rail on which the transaction was submitted."""

    UPI = "upi"
    NEFT = "neft"
    RTGS = "rtgs"
    IMPS = "imps"
    WIRE = "wire"
    CARD = "card"
    CASH = "cash"
    INTERNAL = "internal"
    OTHER = "other"


# ── Origin of the event record ──────────────────────────────────────────────


@unique
class EventOrigin(StrEnum):
    """How the event entered AEGIS-Flow."""

    BANK_FEED = "bank_feed"
    MANUAL_UPLOAD = "manual_upload"
    API_PUSH = "api_push"
    SYNTHETIC = "synthetic"


# ── Fraud case lifecycle ─────────────────────────────────────────────────────


@unique
class CaseStatus(StrEnum):
    """High-level lifecycle state of a fraud case."""

    OPEN = "open"
    UNDER_REVIEW = "under_review"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CLOSED = "closed"


# ── Fraud case origin ───────────────────────────────────────────────────────


@unique
class CaseOrigin(StrEnum):
    """How the fraud case entered AEGIS-Flow."""

    CUSTOMER_REPORT = "customer_report"
    BANK_DETECTION = "bank_detection"
    SHARED_INTELLIGENCE = "shared_intelligence"
    MANUAL_INVESTIGATION = "manual_investigation"
    SYNTHETIC = "synthetic"


# ── Evidence provider taxonomy ───────────────────────────────────────────────


@unique
class EvidenceProviderType(StrEnum):
    """Category of the system or actor that produced an evidence artifact."""

    INGESTION = "ingestion"
    GRAPH_ENGINE = "graph_engine"
    TAINT_ENGINE = "taint_engine"
    ML_MODEL = "ml_model"
    HUMAN_ANALYST = "human_analyst"
    EXTERNAL_SYSTEM = "external_system"
