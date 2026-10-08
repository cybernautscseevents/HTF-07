"""Integration coverage for repository-to-TemporalGraph ingestion wiring."""

from __future__ import annotations

import copy
import json

import pytest

from backend.app.dependencies import get_case_graph_registry
from tests.backend.conftest import (
    VALID_CASE,
    VALID_EVENT_1,
    VALID_EVENT_2,
    VALID_EVENT_3,
)


async def _create_case(client, case_id: str = "case-001") -> None:
    payload = {**VALID_CASE, "case_id": case_id}
    response = await client.post("/api/cases", content=json.dumps(payload))
    assert response.status_code == 201


class TestCaseGraphIntegration:
    @pytest.mark.asyncio
    async def test_case_creation_creates_an_empty_isolated_graph(self, client):
        await _create_case(client)

        graph = get_case_graph_registry().graph("case-001")
        assert graph is not None
        assert graph.node_count == 0
        assert graph.edge_count == 0

    @pytest.mark.asyncio
    async def test_single_event_is_persisted_and_added_to_graph(self, client):
        await _create_case(client)
        response = await client.post(
            "/api/events",
            params={"case_id": "case-001"},
            content=json.dumps(VALID_EVENT_1),
        )
        assert response.status_code == 201

        graph = get_case_graph_registry().graph("case-001")
        assert graph is not None
        edge = graph.get_edge_by_event("evt-001")
        assert (edge.sender_id, edge.receiver_id) == (
            "acct-sender-1", "acct-receiver-1",
        )
        assert graph.node_count == 2
        assert graph.edge_count == 1

    @pytest.mark.asyncio
    async def test_batch_ingestion_updates_graph_and_endpoint(self, client):
        await _create_case(client)
        response = await client.post(
            "/api/events/batch",
            params={"case_id": "case-001"},
            content=json.dumps([VALID_EVENT_1, VALID_EVENT_2]),
        )
        assert response.status_code == 201

        graph_response = await client.get("/api/cases/case-001/graph")
        assert graph_response.status_code == 200
        graph_data = graph_response.json()
        assert graph_data["node_count"] == 3
        assert graph_data["edge_count"] == 2
        assert [edge["event_id"] for edge in graph_data["edges"]] == [
            "evt-001", "evt-002",
        ]

    @pytest.mark.asyncio
    async def test_cases_have_isolated_graph_instances(self, client):
        await _create_case(client, "case-001")
        await _create_case(client, "case-002")
        await client.post(
            "/api/events",
            params={"case_id": "case-001"},
            content=json.dumps(VALID_EVENT_1),
        )
        case_two_event = copy.deepcopy(VALID_EVENT_2)
        case_two_event["event_id"] = "evt-case-002"
        await client.post(
            "/api/events",
            params={"case_id": "case-002"},
            content=json.dumps(case_two_event),
        )

        registry = get_case_graph_registry()
        case_one_graph = registry.graph("case-001")
        case_two_graph = registry.graph("case-002")
        assert case_one_graph is not case_two_graph
        assert [edge.event_id for edge in case_one_graph.events_between(active_only=False)] == [
            "evt-001"
        ]
        assert [edge.event_id for edge in case_two_graph.events_between(active_only=False)] == [
            "evt-case-002"
        ]

    @pytest.mark.asyncio
    async def test_duplicate_event_id_does_not_create_duplicate_graph_edge(self, client):
        await _create_case(client)
        first = await client.post(
            "/api/events",
            params={"case_id": "case-001"},
            content=json.dumps(VALID_EVENT_1),
        )
        duplicate = await client.post(
            "/api/events",
            params={"case_id": "case-001"},
            content=json.dumps(VALID_EVENT_1),
        )

        assert first.status_code == 201
        assert duplicate.status_code == 409
        assert get_case_graph_registry().graph("case-001").edge_count == 1

    @pytest.mark.asyncio
    async def test_timeline_and_graph_hold_the_same_events(self, client):
        await _create_case(client)
        await client.post(
            "/api/events/batch",
            params={"case_id": "case-001"},
            content=json.dumps([VALID_EVENT_1, VALID_EVENT_2, VALID_EVENT_3]),
        )

        timeline = (await client.get("/api/cases/case-001/timeline")).json()
        graph = (await client.get("/api/cases/case-001/graph")).json()
        assert {event["event_id"] for event in timeline} == {
            edge["event_id"] for edge in graph["edges"]
        }
        assert [edge["event_id"] for edge in graph["edges"]] == [
            "evt-003", "evt-001", "evt-002"
        ]

    @pytest.mark.asyncio
    async def test_inactive_events_are_stored_but_excluded_from_active_traversal(
        self, client
    ):
        await _create_case(client)
        pending_event = {**VALID_EVENT_1, "status": "pending"}
        await client.post(
            "/api/events",
            params={"case_id": "case-001"},
            content=json.dumps(pending_event),
        )

        timeline = await client.get("/api/cases/case-001/timeline")
        graph_response = await client.get("/api/cases/case-001/graph")
        graph = get_case_graph_registry().graph("case-001")
        assert [event["event_id"] for event in timeline.json()] == ["evt-001"]
        assert [edge["event_id"] for edge in graph_response.json()["edges"]] == [
            "evt-001"
        ]
        assert graph.outgoing("acct-sender-1") == []
        assert [edge.event_id for edge in graph.outgoing(
            "acct-sender-1", active_only=False
        )] == ["evt-001"]
