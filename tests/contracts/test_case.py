"""
Tests for contracts.case — FraudCase schema.

Covers:
- Zero transaction_ids (case opened before transactions attached)
- Non-empty transaction_ids
- CaseOrigin enum (all valid values, invalid rejected)
- Timestamp validation
- Round-trip serialization
- Rejection of computed fields
"""

from datetime import datetime, timezone, timedelta

import pytest
from pydantic import ValidationError

from contracts.enums import CaseOrigin, CaseStatus
from contracts.case import FraudCase


# ── Fixtures ─────────────────────────────────────────────────────────────────

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc


def _valid_payload() -> dict:
    """Return a minimal valid FraudCase dict (strict-mode compatible)."""
    return {
        "case_id": "case-001",
        "title": "Suspicious UPI chain",
        "origin": CaseOrigin.BANK_DETECTION,
        "status": CaseStatus.OPEN,
        "transaction_ids": ["txn-001", "txn-002"],
        "opened_at": datetime(2026, 10, 8, 15, 0, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 10, 8, 18, 0, 0, tzinfo=UTC),
    }


# ── Happy path ───────────────────────────────────────────────────────────────


class TestFraudCaseValid:
    def test_minimal_valid_with_transactions(self):
        case = FraudCase(**_valid_payload())
        assert case.case_id == "case-001"
        assert case.schema_version == "1.0.0"
        assert len(case.transaction_ids) == 2

    def test_with_description(self):
        data = _valid_payload()
        data["description"] = "Multi-hop laundering cluster"
        case = FraudCase(**data)
        assert case.description == "Multi-hop laundering cluster"

    def test_zero_transactions_valid(self):
        """A case may be opened before transactions are attached."""
        data = _valid_payload()
        data["transaction_ids"] = []
        case = FraudCase(**data)
        assert case.transaction_ids == []

    def test_default_empty_transactions(self):
        """transaction_ids defaults to empty list when omitted."""
        data = _valid_payload()
        del data["transaction_ids"]
        case = FraudCase(**data)
        assert case.transaction_ids == []


# ── Case origin ──────────────────────────────────────────────────────────────


class TestFraudCaseOrigin:
    def test_origin_required(self):
        data = _valid_payload()
        del data["origin"]
        with pytest.raises(ValidationError):
            FraudCase(**data)

    def test_all_valid_origins_accepted(self):
        for origin in CaseOrigin:
            data = _valid_payload()
            data["origin"] = origin
            case = FraudCase(**data)
            assert case.origin == origin

    def test_invalid_origin_rejected(self):
        data = _valid_payload()
        data["origin"] = "psychic_vision"
        with pytest.raises(ValidationError):
            FraudCase(**data)

    def test_raw_string_origin_rejected_in_strict_mode(self):
        data = _valid_payload()
        data["origin"] = "bank_detection"  # string, not CaseOrigin enum
        with pytest.raises(ValidationError):
            FraudCase(**data)

    def test_customer_report_origin(self):
        data = _valid_payload()
        data["origin"] = CaseOrigin.CUSTOMER_REPORT
        case = FraudCase(**data)
        assert case.origin == CaseOrigin.CUSTOMER_REPORT

    def test_shared_intelligence_origin(self):
        data = _valid_payload()
        data["origin"] = CaseOrigin.SHARED_INTELLIGENCE
        case = FraudCase(**data)
        assert case.origin == CaseOrigin.SHARED_INTELLIGENCE


# ── Missing required IDs ────────────────────────────────────────────────────


class TestFraudCaseMissingIds:
    def test_missing_case_id(self):
        data = _valid_payload()
        del data["case_id"]
        with pytest.raises(ValidationError):
            FraudCase(**data)

    def test_empty_case_id(self):
        data = _valid_payload()
        data["case_id"] = ""
        with pytest.raises(ValidationError):
            FraudCase(**data)

    def test_empty_title(self):
        data = _valid_payload()
        data["title"] = ""
        with pytest.raises(ValidationError):
            FraudCase(**data)


# ── Timestamp validation ─────────────────────────────────────────────────────


class TestFraudCaseTimestamp:
    def test_naive_opened_at_rejected(self):
        data = _valid_payload()
        data["opened_at"] = datetime(2026, 10, 8, 15, 0, 0)
        with pytest.raises(ValidationError, match="timezone-aware"):
            FraudCase(**data)

    def test_naive_updated_at_rejected(self):
        data = _valid_payload()
        data["updated_at"] = datetime(2026, 10, 8, 18, 0, 0)
        with pytest.raises(ValidationError, match="timezone-aware"):
            FraudCase(**data)

    def test_non_utc_timezone_preserved(self):
        data = _valid_payload()
        data["opened_at"] = datetime(2026, 10, 8, 20, 30, 0, tzinfo=IST)
        case = FraudCase(**data)
        assert case.opened_at.utcoffset() == timedelta(hours=5, minutes=30)


# ── Enum validation ──────────────────────────────────────────────────────────


class TestFraudCaseEnums:
    def test_unknown_status_rejected(self):
        data = _valid_payload()
        data["status"] = "nonexistent_status"
        with pytest.raises(ValidationError):
            FraudCase(**data)

    def test_all_valid_statuses_accepted(self):
        for status in CaseStatus:
            data = _valid_payload()
            data["status"] = status
            case = FraudCase(**data)
            assert case.status == status

    def test_raw_string_status_rejected_in_strict_mode(self):
        data = _valid_payload()
        data["status"] = "open"  # string, not CaseStatus.OPEN
        with pytest.raises(ValidationError):
            FraudCase(**data)


# ── Serialization round-trip ─────────────────────────────────────────────────


class TestFraudCaseRoundTrip:
    def test_json_round_trip(self):
        case = FraudCase(**_valid_payload())
        json_str = case.model_dump_json()
        restored = FraudCase.model_validate_json(json_str)
        assert restored == case

    def test_json_round_trip_zero_transactions(self):
        data = _valid_payload()
        data["transaction_ids"] = []
        case = FraudCase(**data)
        json_str = case.model_dump_json()
        restored = FraudCase.model_validate_json(json_str)
        assert restored == case
        assert restored.transaction_ids == []

    def test_dict_round_trip(self):
        case = FraudCase(**_valid_payload())
        d = case.model_dump()
        restored = FraudCase.model_validate(d)
        assert restored == case

    def test_sample_json_file_parses(self):
        import pathlib

        sample = (
            pathlib.Path(__file__).resolve().parents[2]
            / "contracts"
            / "examples"
            / "sample_case.json"
        )
        json_str = sample.read_text(encoding="utf-8")
        case = FraudCase.model_validate_json(json_str)
        assert case.case_id == "case-2026-00042"
        assert case.origin == CaseOrigin.BANK_DETECTION


# ── Extra fields forbidden ───────────────────────────────────────────────────


class TestFraudCaseExtraFields:
    def test_extra_field_rejected(self):
        data = _valid_payload()
        data["total_taint"] = 1234567
        with pytest.raises(ValidationError):
            FraudCase(**data)
