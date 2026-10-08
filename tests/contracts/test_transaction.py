"""
Tests for contracts.transaction — TransactionEvent schema.

Covers:
- event_id / transaction_id identity separation
- occurred_at / observed_at dual timestamps
- integer paise precision
- currency validation (INR primary)
- strict enum enforcement
- round-trip serialization
- rejection of computed fields
"""

from datetime import datetime, timezone, timedelta

import pytest
from pydantic import ValidationError

from contracts.enums import EventOrigin, TransactionChannel, TransactionStatus
from contracts.account import AccountReference
from contracts.transaction import TransactionEvent


# ── Fixtures ─────────────────────────────────────────────────────────────────

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc


def _valid_payload() -> dict:
    """Return a minimal valid TransactionEvent dict (strict-mode compatible)."""
    return {
        "event_id": "evt-001",
        "transaction_id": "txn-001",
        "sender": AccountReference(account_id="acct-sender-01"),
        "receiver": AccountReference(account_id="acct-receiver-01"),
        "amount_minor_units": 5000000,  # ₹50,000.00
        "currency": "INR",
        "occurred_at": datetime(2026, 10, 8, 14, 30, 0, tzinfo=UTC),
        "observed_at": datetime(2026, 10, 8, 14, 30, 2, tzinfo=UTC),
        "status": TransactionStatus.COMPLETED,
        "channel": TransactionChannel.UPI,
        "origin": EventOrigin.BANK_FEED,
    }


# ── Happy path ───────────────────────────────────────────────────────────────


class TestTransactionEventValid:
    def test_minimal_valid(self):
        event = TransactionEvent(**_valid_payload())
        assert event.event_id == "evt-001"
        assert event.transaction_id == "txn-001"
        assert event.amount_minor_units == 5000000
        assert event.currency == "INR"
        assert event.schema_version == "1.0.0"

    def test_with_optional_fields(self):
        data = _valid_payload()
        data["reference"] = "UTR-12345"
        data["sender"] = AccountReference(
            account_id="acct-sender-01",
            institution="HDFC Bank",
            label="Alice",
        )
        event = TransactionEvent(**data)
        assert event.reference == "UTR-12345"
        assert event.sender.institution == "HDFC Bank"

    def test_zero_amount_is_valid(self):
        data = _valid_payload()
        data["amount_minor_units"] = 0
        event = TransactionEvent(**data)
        assert event.amount_minor_units == 0

    def test_large_amount_exact(self):
        """Integer minor-unit amounts must remain exact for large values."""
        data = _valid_payload()
        data["amount_minor_units"] = 99_99_99_99_999  # ~₹99,99,99,999.99
        event = TransactionEvent(**data)
        assert event.amount_minor_units == 99_99_99_99_999


# ── Event ID / Transaction ID identity ──────────────────────────────────────


class TestTransactionEventIdentity:
    def test_event_id_required(self):
        data = _valid_payload()
        del data["event_id"]
        with pytest.raises(ValidationError):
            TransactionEvent(**data)

    def test_empty_event_id_rejected(self):
        data = _valid_payload()
        data["event_id"] = ""
        with pytest.raises(ValidationError):
            TransactionEvent(**data)

    def test_transaction_id_is_stable_business_identity(self):
        """transaction_id is the business payment identity, not the event identity."""
        event = TransactionEvent(**_valid_payload())
        assert event.transaction_id == "txn-001"
        assert event.event_id == "evt-001"
        assert event.event_id != event.transaction_id

    def test_multiple_events_can_share_transaction_id(self):
        """Multiple lifecycle observations may share a transaction_id."""
        base = _valid_payload()

        evt_pending = TransactionEvent(
            **{**base, "event_id": "evt-001", "status": TransactionStatus.PENDING}
        )
        evt_completed = TransactionEvent(
            **{**base, "event_id": "evt-002", "status": TransactionStatus.COMPLETED}
        )

        assert evt_pending.transaction_id == evt_completed.transaction_id
        assert evt_pending.event_id != evt_completed.event_id


# ── Negative amount ──────────────────────────────────────────────────────────


class TestTransactionEventNegativeAmount:
    def test_negative_amount_rejected(self):
        data = _valid_payload()
        data["amount_minor_units"] = -1
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            TransactionEvent(**data)


# ── Timestamp validation ─────────────────────────────────────────────────────


class TestTransactionEventTimestamp:
    def test_naive_occurred_at_rejected(self):
        data = _valid_payload()
        data["occurred_at"] = datetime(2026, 10, 8, 14, 30, 0)  # naive
        with pytest.raises(ValidationError, match="timezone-aware"):
            TransactionEvent(**data)

    def test_naive_observed_at_rejected(self):
        data = _valid_payload()
        data["observed_at"] = datetime(2026, 10, 8, 14, 30, 2)  # naive
        with pytest.raises(ValidationError, match="timezone-aware"):
            TransactionEvent(**data)

    def test_non_utc_timezone_preserved_occurred_at(self):
        data = _valid_payload()
        data["occurred_at"] = datetime(2026, 10, 8, 20, 0, 0, tzinfo=IST)
        event = TransactionEvent(**data)
        assert event.occurred_at.tzinfo is not None
        assert event.occurred_at.utcoffset() == timedelta(hours=5, minutes=30)

    def test_non_utc_timezone_preserved_observed_at(self):
        data = _valid_payload()
        data["observed_at"] = datetime(2026, 10, 8, 20, 0, 2, tzinfo=IST)
        event = TransactionEvent(**data)
        assert event.observed_at.utcoffset() == timedelta(hours=5, minutes=30)

    def test_utc_serialization_round_trip(self):
        """UTC timestamps must survive JSON round-trip without offset loss."""
        event = TransactionEvent(**_valid_payload())
        json_str = event.model_dump_json()
        restored = TransactionEvent.model_validate_json(json_str)
        assert restored.occurred_at == event.occurred_at
        assert restored.observed_at == event.observed_at


# ── Missing required IDs ────────────────────────────────────────────────────


class TestTransactionEventMissingIds:
    def test_missing_transaction_id(self):
        data = _valid_payload()
        del data["transaction_id"]
        with pytest.raises(ValidationError):
            TransactionEvent(**data)

    def test_empty_transaction_id(self):
        data = _valid_payload()
        data["transaction_id"] = ""
        with pytest.raises(ValidationError):
            TransactionEvent(**data)

    def test_missing_sender(self):
        data = _valid_payload()
        del data["sender"]
        with pytest.raises(ValidationError):
            TransactionEvent(**data)

    def test_empty_account_id_in_sender(self):
        """Empty account_id must be caught by AccountReference validation."""
        with pytest.raises(ValidationError):
            AccountReference(account_id="")


# ── Enum validation ──────────────────────────────────────────────────────────


class TestTransactionEventEnums:
    def test_unknown_status_rejected(self):
        data = _valid_payload()
        data["status"] = "invalid_status"
        with pytest.raises(ValidationError):
            TransactionEvent(**data)

    def test_unknown_channel_rejected(self):
        data = _valid_payload()
        data["channel"] = "pigeon_post"
        with pytest.raises(ValidationError):
            TransactionEvent(**data)

    def test_unknown_origin_rejected(self):
        data = _valid_payload()
        data["origin"] = "telepathy"
        with pytest.raises(ValidationError):
            TransactionEvent(**data)

    def test_raw_string_enum_rejected_in_strict_mode(self):
        """Strict mode requires actual enum instances, not raw strings."""
        data = _valid_payload()
        data["status"] = "completed"  # string, not TransactionStatus.COMPLETED
        with pytest.raises(ValidationError):
            TransactionEvent(**data)


# ── Currency validation ─────────────────────────────────────────────────────


class TestTransactionEventCurrency:
    def test_inr_accepted(self):
        data = _valid_payload()
        data["currency"] = "INR"
        event = TransactionEvent(**data)
        assert event.currency == "INR"

    def test_lowercase_currency_rejected(self):
        data = _valid_payload()
        data["currency"] = "inr"
        with pytest.raises(ValidationError, match="upper-case"):
            TransactionEvent(**data)

    def test_too_short_currency_rejected(self):
        data = _valid_payload()
        data["currency"] = "IN"
        with pytest.raises(ValidationError):
            TransactionEvent(**data)

    def test_non_inr_currency_accepted_by_schema(self):
        """Schema allows any valid 3-letter upper-case code.
        Multi-currency exponent metadata is deferred to a future version."""
        data = _valid_payload()
        data["currency"] = "USD"
        event = TransactionEvent(**data)
        assert event.currency == "USD"


# ── Serialization round-trip ─────────────────────────────────────────────────


class TestTransactionEventRoundTrip:
    def test_json_round_trip(self):
        event = TransactionEvent(**_valid_payload())
        json_str = event.model_dump_json()
        restored = TransactionEvent.model_validate_json(json_str)
        assert restored == event
        assert restored.amount_minor_units == event.amount_minor_units

    def test_dict_round_trip(self):
        event = TransactionEvent(**_valid_payload())
        d = event.model_dump()
        restored = TransactionEvent.model_validate(d)
        assert restored == event

    def test_sample_json_file_parses(self):
        """The shipped sample_transaction.json must parse via model_validate_json."""
        import pathlib

        sample = (
            pathlib.Path(__file__).resolve().parents[2]
            / "contracts"
            / "examples"
            / "sample_transaction.json"
        )
        json_str = sample.read_text(encoding="utf-8")
        event = TransactionEvent.model_validate_json(json_str)
        assert event.event_id == "evt-20261008-00001"
        assert event.transaction_id == "txn-20261008-00001"

    def test_integer_paise_precision_survives_round_trip(self):
        """Verify that large integer paise amounts survive JSON round-trip exactly."""
        data = _valid_payload()
        data["amount_minor_units"] = 12_34_56_78_901
        event = TransactionEvent(**data)
        json_str = event.model_dump_json()
        restored = TransactionEvent.model_validate_json(json_str)
        assert restored.amount_minor_units == 12_34_56_78_901


# ── Extra fields forbidden ───────────────────────────────────────────────────


class TestTransactionEventExtraFields:
    def test_extra_field_rejected(self):
        data = _valid_payload()
        data["risk_score"] = 0.95  # computed — must not be here
        with pytest.raises(ValidationError):
            TransactionEvent(**data)

    def test_taint_field_rejected(self):
        data = _valid_payload()
        data["taint_amount"] = 42
        with pytest.raises(ValidationError):
            TransactionEvent(**data)
