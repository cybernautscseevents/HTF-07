"""
AEGIS-Flow Synthetic Generator — Ground Truth Module
=====================================================

Defines the external ground-truth metadata schema for synthetic scenarios.
In accordance with system design principles, ground-truth labels are
strictly separated from canonical TransactionEvent observations and stored
in dedicated ScenarioTruth envelopes.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ScenarioTruth(BaseModel):
    """Ground-truth metadata for a single synthetic scenario.

    Used by benchmark suites, taint evaluation, and ML scoring.
    Never embedded in TransactionEvent objects.
    """

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
    )

    scenario_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier for the synthetic scenario (e.g. 'sc-simple-chain-01').",
    )
    scenario_type: str = Field(
        ...,
        min_length=1,
        description="Family name of the scenario (e.g. 'simple_chain', 'smurfing').",
    )
    case_id: str | None = Field(
        default=None,
        description="Linked FraudCase ID, or None if the scenario is purely benign.",
    )
    seed_transaction_ids: list[str] = Field(
        default_factory=list,
        description="Transaction IDs representing the initial injection or fraud seed.",
    )
    fraud_transaction_ids: list[str] = Field(
        default_factory=list,
        description="All transaction IDs confirmed as part of the illicit flow.",
    )
    fraud_accounts: list[str] = Field(
        default_factory=list,
        description="Account IDs participating in the laundering or fraud chain.",
    )
    source_account: str | None = Field(
        default=None,
        description="Primary source or victim account initiating the flow.",
    )
    intended_downstream_path: list[str] = Field(
        default_factory=list,
        description="Primary sequential account path of the flow [source, hop1, ..., exit].",
    )
    intended_next_hop_label: dict[str, str | list[str]] = Field(
        default_factory=dict,
        description="Ground-truth next-hop mapping: account_id -> next hop account ID(s).",
    )
    expected_convergence_account: str | None = Field(
        default=None,
        description="Expected chokepoint or aggregation account where flows converge.",
    )
    injected_fraud_amount: int = Field(
        default=0,
        ge=0,
        description="Total illicit capital injected into the scenario in minor units (paise).",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary scenario-specific truth annotations (e.g. banks, hop latency).",
    )
