"""
conftest.py — shared fixtures for backend API tests.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.main import app
from backend.app.dependencies import reset_repositories


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset in-memory repositories before each test."""
    reset_repositories()
    yield
    reset_repositories()


@pytest.fixture
def client():
    """Synchronous-style async client for FastAPI test requests."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ── Reusable payloads ───────────────────────────────────────────────────────

VALID_CASE = {
    "case_id": "case-001",
    "title": "Suspicious UPI chain",
    "origin": "bank_detection",
    "status": "open",
    "transaction_ids": [],
    "opened_at": "2026-10-08T15:00:00Z",
    "updated_at": "2026-10-08T18:00:00Z",
}

VALID_EVENT_1 = {
    "event_id": "evt-001",
    "transaction_id": "txn-001",
    "reference": "UTR-HDFC-001",
    "sender": {
        "account_id": "acct-sender-1",
        "institution": "HDFC Bank",
        "label": "Sender A",
    },
    "receiver": {
        "account_id": "acct-receiver-1",
        "institution": "ICICI Bank",
        "label": "Receiver B",
    },
    "amount_minor_units": 5000000,
    "currency": "INR",
    "occurred_at": "2026-10-08T14:30:00Z",
    "observed_at": "2026-10-08T14:30:02Z",
    "status": "completed",
    "channel": "upi",
    "origin": "bank_feed",
}

VALID_EVENT_2 = {
    "event_id": "evt-002",
    "transaction_id": "txn-002",
    "reference": "UTR-HDFC-002",
    "sender": {
        "account_id": "acct-receiver-1",
        "institution": "ICICI Bank",
        "label": "Receiver B",
    },
    "receiver": {
        "account_id": "acct-receiver-2",
        "institution": "SBI",
        "label": "Receiver C",
    },
    "amount_minor_units": 3000000,
    "currency": "INR",
    "occurred_at": "2026-10-08T15:00:00Z",
    "observed_at": "2026-10-08T15:00:01Z",
    "status": "completed",
    "channel": "upi",
    "origin": "bank_feed",
}

VALID_EVENT_3 = {
    "event_id": "evt-003",
    "transaction_id": "txn-003",
    "sender": {
        "account_id": "acct-receiver-2",
        "institution": "SBI",
    },
    "receiver": {
        "account_id": "acct-receiver-3",
        "institution": "Axis Bank",
    },
    "amount_minor_units": 1000000,
    "currency": "INR",
    "occurred_at": "2026-10-08T13:00:00Z",
    "observed_at": "2026-10-08T13:00:01Z",
    "status": "completed",
    "channel": "neft",
    "origin": "bank_feed",
}
