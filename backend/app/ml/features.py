"""
AEGIS-Flow ML Intelligence Layer — Feature Extraction
=====================================================

Reusable feature extraction from TemporalGraph for account risk scoring
and next-hop destination prediction.

Temporal Causality & Cleanliness Guarantees:
--------------------------------------------
1. Strict Temporal Filtering:
   Every query against TemporalGraph MUST supply `end=as_of_time`.
   No edge with `occurred_at > as_of_time` is ever examined.
2. Zero Ground-Truth Leakage:
   Features never access `ScenarioTruth`, `FraudCase` labels, or fraud flags.
   Account IDs are treated as opaque strings without parsing semantic substrings.
3. Cold-Start Segmentation:
   Explicitly captures historical observation span, pre-incident transaction
   counts, and classifies evidence maturity.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import math
from typing import Sequence

from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.graph.temporal_index import EdgeData
from backend.app.ml.schemas import EvidenceMaturity

# Ordered list of feature names for deterministic feature matrix creation.
ACCOUNT_FEATURE_NAMES: list[str] = [
    # ── Graph / Topology ──────────────────────────────────────────────────
    "in_degree",
    "out_degree",
    "total_degree",
    "unique_senders",
    "unique_receivers",
    "unique_counterparties",
    "bilateral_counterparties",
    "fan_in_ratio",
    "fan_out_ratio",
    "institution_diversity",
    "cross_institution_tx_ratio",
    # ── Temporal / Behavioral ─────────────────────────────────────────────
    "lifespan_seconds",
    "active_duration_seconds",
    "tx_velocity_per_hour",
    "min_pass_through_seconds",
    "median_pass_through_seconds",
    "has_rapid_pass_through",
    "tx_count_last_1h",
    "tx_count_last_24h",
    "burst_ratio_1h",
    "time_since_last_tx_seconds",
    # ── Money-Flow ────────────────────────────────────────────────────────
    "total_inbound_amount",
    "total_outbound_amount",
    "net_flow_amount",
    "forwarding_ratio",
    "mean_inbound_amount",
    "mean_outbound_amount",
    "max_inbound_amount",
    "max_outbound_amount",
    "inbound_outbound_amount_ratio",
    # ── Cold-Start & History ──────────────────────────────────────────────
    "historical_tx_count",
    "historical_duration_seconds",
    "has_historical_profile",
    "is_cold_start",
    "evidence_maturity_level",
]

NEXT_HOP_FEATURE_NAMES: list[str] = [
    "past_transfers_count",
    "past_transfer_volume",
    "time_since_last_transfer_seconds",
    "shared_counterparties_count",
    "jaccard_similarity",
    "candidate_in_degree",
    "candidate_out_degree",
    "candidate_total_inbound",
    "candidate_forwarding_ratio",
    "same_institution",
]


def determine_evidence_maturity(
    total_tx_count: int,
    historical_tx_count: int,
    has_historical_profile: bool,
) -> EvidenceMaturity:
    """Classify the evidence maturity level for an account."""
    if has_historical_profile and total_tx_count >= 5:
        return EvidenceMaturity.STRONG_HISTORY
    if total_tx_count <= 1:
        return EvidenceMaturity.LIMITED_EVIDENCE
    return EvidenceMaturity.FLOW_DOMINANT


def extract_account_features(
    graph: TemporalGraph,
    account_id: str,
    as_of_time: datetime,
    history_cutoff_time: datetime | None = None,
    institution_map: dict[str, str] | None = None,
) -> dict[str, float]:
    """Extract temporal, behavioral, and money-flow features for an account.

    Parameters
    ----------
    graph : TemporalGraph
        Graph instance to query.
    account_id : str
        Target account opaque ID.
    as_of_time : datetime
        Strict upper bound on event time (causality barrier).
    history_cutoff_time : datetime, optional
        Pre-incident time barrier. Events with occurred_at < history_cutoff_time
        are counted as historical baseline activity.
    institution_map : dict[str, str], optional
        Optional mapping from account_id to institution/BIC name.
    """
    if as_of_time.tzinfo is None:
        raise ValueError("as_of_time must be timezone-aware.")

    # 1. Fetch strictly causal incoming and outgoing edges
    incoming_edges: list[EdgeData] = graph.incoming(
        account_id, end=as_of_time, active_only=True
    )
    outgoing_edges: list[EdgeData] = graph.outgoing(
        account_id, end=as_of_time, active_only=True
    )

    in_degree = len(incoming_edges)
    out_degree = len(outgoing_edges)
    total_degree = in_degree + out_degree

    senders = {e.sender_id for e in incoming_edges}
    receivers = {e.receiver_id for e in outgoing_edges}
    unique_counterparties = len(senders | receivers)
    bilateral_counterparties = len(senders & receivers)

    fan_in_ratio = float(in_degree) / max(1.0, float(total_degree))
    fan_out_ratio = float(out_degree) / max(1.0, float(total_degree))

    # Institution features
    inst_map = institution_map or {}
    all_counterparty_ids = senders | receivers
    distinct_institutions = {
        inst_map[cid] for cid in all_counterparty_ids if cid in inst_map
    }
    institution_diversity = float(len(distinct_institutions))

    my_inst = inst_map.get(account_id)
    if my_inst and all_counterparty_ids:
        cross_tx = sum(
            1 for e in (incoming_edges + outgoing_edges)
            if inst_map.get(e.sender_id) != inst_map.get(e.receiver_id)
        )
        cross_institution_tx_ratio = float(cross_tx) / max(1.0, float(total_degree))
    else:
        cross_institution_tx_ratio = 0.0

    # 2. Temporal & Behavioral
    all_edges = sorted(incoming_edges + outgoing_edges, key=lambda e: e.occurred_at)

    if all_edges:
        first_tx_time = all_edges[0].occurred_at
        last_tx_time = all_edges[-1].occurred_at
        lifespan_seconds = max(0.0, (as_of_time - first_tx_time).total_seconds())
        active_duration_seconds = max(0.0, (last_tx_time - first_tx_time).total_seconds())
        tx_velocity_per_hour = float(total_degree) / max(1.0, active_duration_seconds / 3600.0)
        time_since_last_tx_seconds = max(0.0, (as_of_time - last_tx_time).total_seconds())
    else:
        lifespan_seconds = 0.0
        active_duration_seconds = 0.0
        tx_velocity_per_hour = 0.0
        time_since_last_tx_seconds = 86400.0 * 30.0

    # Pass-through delays (pairing incoming to subsequent outgoing)
    delays: list[float] = []
    if incoming_edges and outgoing_edges:
        out_idx = 0
        for in_e in incoming_edges:
            while out_idx < len(outgoing_edges) and outgoing_edges[out_idx].occurred_at < in_e.occurred_at:
                out_idx += 1
            for k in range(out_idx, len(outgoing_edges)):
                out_e = outgoing_edges[k]
                d = (out_e.occurred_at - in_e.occurred_at).total_seconds()
                if d >= 0:
                    delays.append(d)
                    break

    sentinel_delay = 86400.0  # 24 hours default when no pass-through observed
    if delays:
        delays_sorted = sorted(delays)
        min_pass_through_seconds = delays_sorted[0]
        mid = len(delays_sorted) // 2
        median_pass_through_seconds = (
            delays_sorted[mid]
            if len(delays_sorted) % 2 != 0
            else (delays_sorted[mid - 1] + delays_sorted[mid]) / 2.0
        )
        has_rapid_pass_through = 1.0 if min_pass_through_seconds <= 300.0 else 0.0
    else:
        min_pass_through_seconds = sentinel_delay
        median_pass_through_seconds = sentinel_delay
        has_rapid_pass_through = 0.0

    # Rolling window counts
    one_hour_ago = as_of_time - timedelta(hours=1)
    twenty_four_hours_ago = as_of_time - timedelta(hours=24)
    tx_count_last_1h = sum(1 for e in all_edges if e.occurred_at >= one_hour_ago)
    tx_count_last_24h = sum(1 for e in all_edges if e.occurred_at >= twenty_four_hours_ago)
    burst_ratio_1h = float(tx_count_last_1h) / max(1.0, float(total_degree))

    # 3. Money-Flow
    total_inbound = sum(e.amount_minor_units for e in incoming_edges)
    total_outbound = sum(e.amount_minor_units for e in outgoing_edges)
    net_flow = total_inbound - total_outbound
    if total_inbound > 0:
        forwarding_ratio = min(1.0, float(total_outbound) / float(total_inbound))
    else:
        forwarding_ratio = 0.0

    mean_inbound = float(total_inbound) / max(1.0, float(in_degree))
    mean_outbound = float(total_outbound) / max(1.0, float(out_degree))
    max_inbound = float(max((e.amount_minor_units for e in incoming_edges), default=0))
    max_outbound = float(max((e.amount_minor_units for e in outgoing_edges), default=0))

    if total_inbound == 0 and total_outbound == 0:
        inbound_outbound_ratio = 1.0
    else:
        inbound_outbound_ratio = float(min(total_inbound, total_outbound)) / max(
            1.0, float(max(total_inbound, total_outbound))
        )

    # 4. Cold-Start & History
    if history_cutoff_time is not None:
        hist_edges = [e for e in all_edges if e.occurred_at < history_cutoff_time]
    else:
        # If no cutoff given, consider transactions older than 24 hours as history
        hist_edges = [e for e in all_edges if e.occurred_at < (as_of_time - timedelta(hours=24))]

    historical_tx_count = len(hist_edges)
    if hist_edges:
        hist_first = hist_edges[0].occurred_at
        hist_last = hist_edges[-1].occurred_at
        historical_duration_seconds = max(0.0, (hist_last - hist_first).total_seconds())
    else:
        historical_duration_seconds = 0.0

    has_historical_profile = (
        1.0 if (historical_tx_count >= 3 and historical_duration_seconds >= 86400.0) else 0.0
    )
    is_cold_start = 1.0 if historical_tx_count == 0 else 0.0

    # Evidence maturity mapping: STRONG=2, FLOW_DOMINANT=1, LIMITED=0
    maturity = determine_evidence_maturity(
        total_tx_count=total_degree,
        historical_tx_count=historical_tx_count,
        has_historical_profile=bool(has_historical_profile),
    )
    maturity_num = 2.0 if maturity == EvidenceMaturity.STRONG_HISTORY else (
        1.0 if maturity == EvidenceMaturity.FLOW_DOMINANT else 0.0
    )

    return {
        "in_degree": float(in_degree),
        "out_degree": float(out_degree),
        "total_degree": float(total_degree),
        "unique_senders": float(len(senders)),
        "unique_receivers": float(len(receivers)),
        "unique_counterparties": float(unique_counterparties),
        "bilateral_counterparties": float(bilateral_counterparties),
        "fan_in_ratio": fan_in_ratio,
        "fan_out_ratio": fan_out_ratio,
        "institution_diversity": institution_diversity,
        "cross_institution_tx_ratio": cross_institution_tx_ratio,
        "lifespan_seconds": lifespan_seconds,
        "active_duration_seconds": active_duration_seconds,
        "tx_velocity_per_hour": tx_velocity_per_hour,
        "min_pass_through_seconds": min_pass_through_seconds,
        "median_pass_through_seconds": median_pass_through_seconds,
        "has_rapid_pass_through": has_rapid_pass_through,
        "tx_count_last_1h": float(tx_count_last_1h),
        "tx_count_last_24h": float(tx_count_last_24h),
        "burst_ratio_1h": burst_ratio_1h,
        "time_since_last_tx_seconds": time_since_last_tx_seconds,
        "total_inbound_amount": float(total_inbound),
        "total_outbound_amount": float(total_outbound),
        "net_flow_amount": float(net_flow),
        "forwarding_ratio": forwarding_ratio,
        "mean_inbound_amount": mean_inbound,
        "mean_outbound_amount": mean_outbound,
        "max_inbound_amount": max_inbound,
        "max_outbound_amount": max_outbound,
        "inbound_outbound_amount_ratio": inbound_outbound_ratio,
        "historical_tx_count": float(historical_tx_count),
        "historical_duration_seconds": historical_duration_seconds,
        "has_historical_profile": has_historical_profile,
        "is_cold_start": is_cold_start,
        "evidence_maturity_level": maturity_num,
    }


def extract_next_hop_candidate_features(
    graph: TemporalGraph,
    source_id: str,
    candidate_id: str,
    as_of_time: datetime,
    institution_map: dict[str, str] | None = None,
) -> dict[str, float]:
    """Extract pairwise features between source_id and candidate_id up to as_of_time."""
    if as_of_time.tzinfo is None:
        raise ValueError("as_of_time must be timezone-aware.")

    # 1. Past direct interaction
    outgoing_from_source = graph.outgoing(source_id, end=as_of_time, active_only=True)
    direct_to_candidate = [e for e in outgoing_from_source if e.receiver_id == candidate_id]

    past_transfers_count = float(len(direct_to_candidate))
    past_transfer_volume = float(sum(e.amount_minor_units for e in direct_to_candidate))
    if direct_to_candidate:
        last_t = max(e.occurred_at for e in direct_to_candidate)
        time_since_last_transfer_seconds = max(0.0, (as_of_time - last_t).total_seconds())
    else:
        time_since_last_transfer_seconds = 86400.0 * 30.0

    # 2. Shared counterparties (Jaccard)
    source_counterparties = {e.sender_id for e in graph.incoming(source_id, end=as_of_time, active_only=True)} | {
        e.receiver_id for e in outgoing_from_source
    }
    cand_incoming = graph.incoming(candidate_id, end=as_of_time, active_only=True)
    cand_outgoing = graph.outgoing(candidate_id, end=as_of_time, active_only=True)
    cand_counterparties = {e.sender_id for e in cand_incoming} | {e.receiver_id for e in cand_outgoing}

    intersection = source_counterparties & cand_counterparties
    union = source_counterparties | cand_counterparties
    shared_counterparties_count = float(len(intersection))
    jaccard_similarity = float(len(intersection)) / max(1.0, float(len(union)))

    # 3. Candidate node activity
    cand_in_degree = float(len(cand_incoming))
    cand_out_degree = float(len(cand_outgoing))
    cand_total_inbound = float(sum(e.amount_minor_units for e in cand_incoming))
    cand_total_outbound = float(sum(e.amount_minor_units for e in cand_outgoing))
    cand_forwarding_ratio = cand_total_outbound / max(1.0, cand_total_inbound)

    # 4. Same institution
    inst_map = institution_map or {}
    src_inst = inst_map.get(source_id)
    cand_inst = inst_map.get(candidate_id)
    same_inst = 1.0 if (src_inst and cand_inst and src_inst == cand_inst) else 0.0

    return {
        "past_transfers_count": past_transfers_count,
        "past_transfer_volume": past_transfer_volume,
        "time_since_last_transfer_seconds": time_since_last_transfer_seconds,
        "shared_counterparties_count": shared_counterparties_count,
        "jaccard_similarity": jaccard_similarity,
        "candidate_in_degree": cand_in_degree,
        "candidate_out_degree": cand_out_degree,
        "candidate_total_inbound": cand_total_inbound,
        "candidate_forwarding_ratio": cand_forwarding_ratio,
        "same_institution": same_inst,
    }
