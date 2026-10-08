"""
Tests for contracts.evidence — EvidenceEnvelope schema.
"""

import json
from datetime import datetime, timezone, timedelta

import pytest
from pydantic import ValidationError

from contracts.enums import EvidenceProviderType
from contracts.evidence import EvidenceEnvelope


# ── Fixtures ─────────────────────────────────────────────────────────────────

IST = timezone(timedelta(hours=5, minutes=30))


def _valid_payload() -> dict:
    """Return a minimal valid EvidenceEnvelope dict (strict-mode compatible)."""
    return {
        "evidence_id": "ev-001",
        "case_id": "case-001",
        "provider_type": EvidenceProviderType.GRAPH_ENGINE,
        "provider_name": "temporal-graph-builder-v1",
        "summary": "Subgraph constructed with 5 nodes.",
        "body": {"node_count": 5, "edge_count": 4},
        "created_at": datetime(2026, 10, 8, 19, 0, 0, tzinfo=timezone.utc),
    }


# ── Happy path ───────────────────────────────────────────────────────────────


class TestEvidenceEnvelopeValid:
    def test_minimal_valid(self):
        ev = EvidenceEnvelope(**_valid_payload())
        assert ev.evidence_id == "ev-001"
        assert ev.schema_version == "1.0.0"
        assert ev.body["node_count"] == 5

    def test_all_provider_types(self):
        for pt in EvidenceProviderType:
            data = _valid_payload()
            data["provider_type"] = pt
            ev = EvidenceEnvelope(**data)
            assert ev.provider_type == pt


# ── Missing required IDs ────────────────────────────────────────────────────


class TestEvidenceEnvelopeMissingIds:
    def test_missing_evidence_id(self):
        data = _valid_payload()
        del data["evidence_id"]
        with pytest.raises(ValidationError):
            EvidenceEnvelope(**data)

    def test_empty_evidence_id(self):
        data = _valid_payload()
        data["evidence_id"] = ""
        with pytest.raises(ValidationError):
            EvidenceEnvelope(**data)

    def test_missing_case_id(self):
        data = _valid_payload()
        del data["case_id"]
        with pytest.raises(ValidationError):
            EvidenceEnvelope(**data)

    def test_empty_provider_name(self):
        data = _valid_payload()
        data["provider_name"] = ""
        with pytest.raises(ValidationError):
            EvidenceEnvelope(**data)

    def test_empty_summary(self):
        data = _valid_payload()
        data["summary"] = ""
        with pytest.raises(ValidationError):
            EvidenceEnvelope(**data)


# ── Timestamp validation ─────────────────────────────────────────────────────


class TestEvidenceEnvelopeTimestamp:
    def test_naive_created_at_rejected(self):
        data = _valid_payload()
        data["created_at"] = datetime(2026, 10, 8, 19, 0, 0)
        with pytest.raises(ValidationError, match="timezone-aware"):
            EvidenceEnvelope(**data)

    def test_non_utc_timezone_preserved(self):
        data = _valid_payload()
        data["created_at"] = datetime(2026, 10, 9, 0, 30, 0, tzinfo=IST)
        ev = EvidenceEnvelope(**data)
        assert ev.created_at.utcoffset() == timedelta(hours=5, minutes=30)


# ── Enum validation ──────────────────────────────────────────────────────────


class TestEvidenceEnvelopeEnums:
    def test_unknown_provider_type_rejected(self):
        data = _valid_payload()
        data["provider_type"] = "crystal_ball"
        with pytest.raises(ValidationError):
            EvidenceEnvelope(**data)

    def test_raw_string_enum_rejected_in_strict_mode(self):
        data = _valid_payload()
        data["provider_type"] = "graph_engine"  # string, not enum
        with pytest.raises(ValidationError):
            EvidenceEnvelope(**data)


# ── Serialization round-trip ─────────────────────────────────────────────────


class TestEvidenceEnvelopeRoundTrip:
    def test_json_round_trip(self):
        ev = EvidenceEnvelope(**_valid_payload())
        json_str = ev.model_dump_json()
        restored = EvidenceEnvelope.model_validate_json(json_str)
        assert restored == ev

    def test_dict_round_trip(self):
        ev = EvidenceEnvelope(**_valid_payload())
        d = ev.model_dump()
        restored = EvidenceEnvelope.model_validate(d)
        assert restored == ev

    def test_sample_json_file_parses(self):
        import pathlib

        sample = (
            pathlib.Path(__file__).resolve().parents[2]
            / "contracts"
            / "examples"
            / "sample_evidence.json"
        )
        json_str = sample.read_text(encoding="utf-8")
        ev = EvidenceEnvelope.model_validate_json(json_str)
        assert ev.evidence_id == "ev-2026-00042-001"


# ── Extra fields forbidden ───────────────────────────────────────────────────


class TestEvidenceEnvelopeExtraFields:
    def test_extra_field_rejected(self):
        data = _valid_payload()
        data["confidence_score"] = 0.97
        with pytest.raises(ValidationError):
            EvidenceEnvelope(**data)
