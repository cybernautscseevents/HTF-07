"""
AEGIS-Flow — Temporal Graph Engine
===================================

Deterministic temporal multigraph engine for financial flow analysis.

Public API
----------
* :class:`TemporalGraph` — core directed multigraph (accounts → edges).
* :class:`EdgeData` — lightweight frozen edge payload.
* :func:`temporal_downstream` — BFS downstream traversal.
* :func:`find_temporal_paths` — DFS temporal path discovery.
* :func:`detect_fan_out` / :func:`detect_fan_in` — structural motifs.
* :func:`detect_rapid_pass_through` — mule-behavior detection.
* :func:`detect_fan_out_fan_in` — compound layering motif.
"""

from backend.app.graph.temporal_index import EdgeData, TemporalIndex
from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.graph.traversal import temporal_downstream, find_temporal_paths
from backend.app.graph.motifs import (
    FanOutMotif,
    FanInMotif,
    PassThroughMotif,
    FanOutFanInMotif,
    detect_fan_out,
    detect_fan_in,
    detect_rapid_pass_through,
    detect_fan_out_fan_in,
)

__all__ = [
    # Core
    "EdgeData",
    "TemporalIndex",
    "TemporalGraph",
    # Traversal
    "temporal_downstream",
    "find_temporal_paths",
    # Motifs
    "FanOutMotif",
    "FanInMotif",
    "PassThroughMotif",
    "FanOutFanInMotif",
    "detect_fan_out",
    "detect_fan_in",
    "detect_rapid_pass_through",
    "detect_fan_out_fan_in",
]
