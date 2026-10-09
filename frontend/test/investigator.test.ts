import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  minorUnitsToMajor,
  formatMinorUnits,
  formatCompactINR,
  formatPaise,
} from "../src/lib/currency.ts";
import { ApiClient, ApiError } from "../src/lib/api/client.ts";
import {
  DEMO_CASE,
  DEMO_EVENTS,
  DEMO_DEFAULT_DECISION_TIME,
  getDemoAnalysisRequest,
  loadDemoScenario,
} from "../src/lib/demo/scenario.ts";
import {
  getStageBadge,
  isAnalysisStale,
  summarizeRecommendationTradeOff,
  formatInterventionExplanation,
} from "../src/lib/mappers/analysisMapper.ts";
import { buildCytoscapeElements } from "../src/lib/mappers/graphMapper.ts";
import type {
  InvestigationAnalysisResponse,
  CandidateRecommendation,
} from "../src/types/index.ts";

describe("AEGIS-Flow Investigator Test Suite", () => {
  // ── 1. Minor-Unit Currency Formatting ──────────────────────────────────────
  describe("Currency Formatting & Minor Units", () => {
    it("converts integer paise minor units to major rupees accurately", () => {
      assert.equal(minorUnitsToMajor(50_000_000), 500_000);
      assert.equal(minorUnitsToMajor(100), 1);
      assert.equal(minorUnitsToMajor(0), 0);
      assert.equal(minorUnitsToMajor(null), 0);
      assert.equal(minorUnitsToMajor(undefined), 0);
    });

    it("formats minor units to user-facing INR strings", () => {
      const formatted = formatMinorUnits(50_000_000, "INR");
      assert.match(formatted, /5,00,000/);
      assert.match(formatted, /₹/);

      const zero = formatMinorUnits(0, "INR");
      assert.match(zero, /₹0\.00/);

      const nil = formatMinorUnits(null, "INR");
      assert.match(nil, /₹0\.00/);
    });

    it("formats compact INR with Lakh and Crore denominations", () => {
      assert.equal(formatCompactINR(50_000_000), "₹5.00 L"); // ₹5 Lakh
      assert.equal(formatCompactINR(1_000_000_000), "₹1.00 Cr"); // ₹1 Crore
      assert.equal(formatCompactINR(500_000), "₹5.0 K"); // ₹5,000
      assert.equal(formatCompactINR(null), "₹0");
    });

    it("formats exact integer paise labels for forensic clarity", () => {
      assert.equal(formatPaise(50_000_000), "5,00,00,000 paise");
      assert.equal(formatPaise(0), "0 paise");
      assert.equal(formatPaise(null), "0 paise");
    });
  });

  // ── 2. API Client Serialization & Validation ──────────────────────────────
  describe("API Client & Error Serialization", () => {
    it("initializes with configurable API base URL", () => {
      const client = new ApiClient("http://test-server:9000/");
      // @ts-expect-error accessing private property for verification
      assert.equal(client.baseUrl, "http://test-server:9000");
    });

    it("serializes ApiError with HTTP status and detail message", () => {
      const error = new ApiError(404, "Case 'case-xyz' not found", { case_id: "case-xyz" });
      assert.equal(error.status, 404);
      assert.equal(error.detail, "Case 'case-xyz' not found");
      assert.match(error.message, /\[404\]: Case 'case-xyz' not found/);
    });

    it("handles simulated network failure without inventing successful responses", async () => {
      const badClient = new ApiClient("http://127.0.0.1:59999"); // unreachable port
      await assert.rejects(
        async () => {
          await badClient.health();
        },
        (err: unknown) => {
          assert(err instanceof ApiError);
          assert.equal((err as ApiError).status, 0);
          assert.match((err as ApiError).detail, /Network failure/);
          return true;
        }
      );
    });
  });

  // ── 3. Deterministic Demo Scenario Workflow ────────────────────────────────
  describe("Deterministic Demo Scenario", () => {
    it("provides curated synthetic demo case with strict contracts", () => {
      assert.equal(DEMO_CASE.schema_version, "1.0.0");
      assert.equal(DEMO_CASE.case_id, "case-demo-synthetic-001");
      assert.equal(DEMO_CASE.origin, "synthetic");
      assert.equal(DEMO_CASE.status, "open");
      assert.equal(DEMO_CASE.transaction_ids.length, 7);
    });

    it("includes 7 sequential transactions modeling multi-stage branching and clean commingling", () => {
      assert.equal(DEMO_EVENTS.length, 7);

      // Victim -> Alpha seed
      const e1 = DEMO_EVENTS[0];
      assert.equal(e1.sender.account_id, "Victim-Corp-99");
      assert.equal(e1.receiver.account_id, "Mule-Alpha-101");
      assert.equal(e1.amount_minor_units, 50_000_000);

      // Clean commingling deposit
      const e4 = DEMO_EVENTS[3];
      assert.equal(e4.sender.account_id, "Clean-Merchant-505");
      assert.equal(e4.receiver.account_id, "Mule-Beta-202");

      // Final cash-out exit sink
      const e7 = DEMO_EVENTS[6];
      assert.equal(e7.sender.account_id, "Mule-Delta-404");
      assert.equal(e7.receiver.account_id, "Exit-CryptoDesk-909");
    });

    it("constructs bounded, valid analysis request for the demo case", () => {
      const req = getDemoAnalysisRequest(DEMO_DEFAULT_DECISION_TIME);
      assert.equal(req.simulation_timestamp, DEMO_DEFAULT_DECISION_TIME);
      assert.equal(req.taint_seeds[0].transaction_id, "tx-seed-1001");
      assert.equal(req.taint_seeds[0].tainted_amount_minor_units, 50_000_000);
      assert.deepEqual(req.sink_account_ids, ["Exit-CryptoDesk-909"]);
    });

    it("safely loads demo scenario idempotently against a mock client", async () => {
      let caseExists = false;
      let createCallCount = 0;
      let batchIngestCount = 0;

      const mockClient = {
        getCase: async () => {
          if (caseExists) return DEMO_CASE;
          throw new ApiError(404, "Not found");
        },
        createCase: async (c: typeof DEMO_CASE) => {
          caseExists = true;
          createCallCount++;
          return c;
        },
        ingestBatch: async (events: typeof DEMO_EVENTS) => {
          batchIngestCount++;
          return { accepted: events.length, event_ids: events.map((e) => e.event_id) };
        },
        getTimeline: async () => DEMO_EVENTS,
      } as unknown as ApiClient;

      const result1 = await loadDemoScenario(mockClient);
      assert.equal(result1.case.case_id, "case-demo-synthetic-001");
      assert.equal(result1.eventsCount, 7);
      assert.equal(createCallCount, 1);
      assert.equal(batchIngestCount, 1);

      // Subsequent call does not recreate case
      const result2 = await loadDemoScenario(mockClient);
      assert.equal(result2.case.case_id, "case-demo-synthetic-001");
      assert.equal(createCallCount, 1); // Still 1!
    });
  });

  // ── 4. Stage Status and Staleness Mapping ──────────────────────────────────
  describe("Analysis Mappers & Operational Diagnostics", () => {
    it("maps operational stage statuses to appropriate badge styles", () => {
      assert.equal(getStageBadge("available").variant, "success");
      assert.equal(getStageBadge("completed").variant, "success");
      assert.equal(getStageBadge("insufficient_evidence").variant, "warning");
      assert.equal(getStageBadge("infeasible").variant, "warning");
      assert.equal(getStageBadge("unavailable").variant, "neutral");
      assert.equal(getStageBadge("failed").variant, "danger");
    });

    it("detects when displayed analysis is stale relative to decision time T", () => {
      const mockAnalysis = {
        simulation_timestamp: "2026-10-09T08:15:00Z",
      } as InvestigationAnalysisResponse;

      assert.equal(isAnalysisStale(mockAnalysis, "2026-10-09T08:15:00Z"), false);
      assert.equal(isAnalysisStale(mockAnalysis, "2026-10-09T08:30:00Z"), true);
      assert.equal(isAnalysisStale(null, "2026-10-09T08:30:00Z"), false);
    });

    it("summarizes candidate trade-offs in plain language", () => {
      const candZeroCollateral: CandidateRecommendation = {
        intervention_id: "int-1",
        intervention_type: "edge_hold",
        modeled_tainted_capital_intercepted: 50_000_000,
        modeled_legitimate_capital_affected: 0,
        remaining_downstream_taint: 0,
        number_of_affected_edges: 1,
        number_of_affected_accounts: 2,
        provenance_confidence: 1.0,
        recovery_efficiency: "Infinity",
        policy_feasible: true,
        explanation: "Clean cut",
      };
      const summary1 = summarizeRecommendationTradeOff(candZeroCollateral);
      assert.match(summary1, /zero legitimate collateral/);

      const candWithCollateral: CandidateRecommendation = {
        ...candZeroCollateral,
        modeled_legitimate_capital_affected: 10_000_000,
      };
      const summary2 = summarizeRecommendationTradeOff(candWithCollateral);
      assert.match(summary2, /collateral affected/);
      assert.match(summary2, /5\.0x efficiency/);
    });

    it("formats investigator plain-language intervention explanations with accurate amounts", () => {
      const candidate: CandidateRecommendation = {
        intervention_id: "int-opt-99",
        intervention_type: "edge_hold",
        target_event_id: "ev-demo-002",
        modeled_tainted_capital_intercepted: 50_000_000,
        modeled_legitimate_capital_affected: 2_000_000,
        remaining_downstream_taint: 0,
        number_of_affected_edges: 1,
        number_of_affected_accounts: 2,
        provenance_confidence: 0.95,
        recovery_efficiency: "25.0",
        policy_feasible: true,
        explanation: "Primary chokepoint hold",
      };

      const explanation = formatInterventionExplanation(candidate, "2026-10-09T08:15:00Z");
      assert.match(explanation, /Modelled intervention at transfer ev-demo-002/);
      assert.match(explanation, /intercept/);
      assert.match(explanation, /5,00,000/);
      assert.match(explanation, /affecting an estimated/);
      assert.match(explanation, /20,000/);
      assert.match(explanation, /evaluated at decision time 08:15:00 UTC/);
    });
  });

  // ── 5. Graph Mapping: Observed vs Forecast Styling ─────────────────────────
  describe("Graph Element Mapping & Distinction", () => {
    it("handles empty case and empty events without crashing", () => {
      const elements = buildCytoscapeElements({
        events: [],
        analysis: null,
      });
      assert.deepEqual(elements, []);
    });

    it("distinguishes historical facts (<= T) from later observations (> T)", () => {
      const decisionTime = "2026-10-09T08:15:00Z";
      const elements = buildCytoscapeElements({
        events: DEMO_EVENTS,
        analysis: null,
        decisionTimestamp: decisionTime,
      });

      // Filter edges
      const edges = elements.filter((el) => el.data.source && el.data.target);
      assert.equal(edges.length, 7);

      // Event 1 (08:00) and Event 2 (08:15) should be historical
      const e1 = edges.find((e) => e.data.id === "ev-demo-001");
      assert.equal(e1?.data.isAvailableAtT, true);
      assert.match(e1?.classes || "", /historical/);

      // Event 3 (08:20) should be later-observation
      const e3 = edges.find((e) => e.data.id === "ev-demo-003");
      assert.equal(e3?.data.isAvailableAtT, false);
      assert.match(e3?.classes || "", /later-observation/);
    });

    it("applies dashed styling and probability labels to forecast edges", () => {
      const mockAnalysis = {
        taint_summary: { current_tainted_accounts: ["Mule-Delta-404"] },
        risk_predictions: [],
        forecast_report: {
          status: "available",
          paths_generated_count: 1,
          scenarios_evaluated_count: 1,
          paths: [
            {
              path_id: "path-fc-1",
              source_account_id: "Mule-Delta-404",
              cumulative_probability: 0.75,
              accounts_sequence: ["Mule-Delta-404", "Exit-CryptoDesk-909"],
              hops: [
                {
                  from_account_id: "Mule-Delta-404",
                  to_account_id: "Exit-CryptoDesk-909",
                  amount_minor_units: 50_000_000,
                  probability: 0.75,
                  occurred_at: "2026-10-09T09:45:00Z",
                },
              ],
            },
          ],
        },
      } as unknown as InvestigationAnalysisResponse;

      const elements = buildCytoscapeElements({
        events: DEMO_EVENTS,
        analysis: mockAnalysis,
        showForecasts: true,
      });

      const forecastEdge = elements.find((el) => el.data.isForecast === true);
      assert.ok(forecastEdge, "Forecast edge must be present in elements");
      assert.match(forecastEdge?.classes || "", /forecast-edge/);
      assert.equal(forecastEdge?.data.probability, 0.75);
      assert.match(String(forecastEdge?.data.label), /Forecast 75%/);
    });

    it("highlights min-cut chokepoint edges distinctly", () => {
      const mockAnalysis = {
        taint_summary: { current_tainted_accounts: [] },
        chokepoint_report: {
          status: "optimal_cut_found",
          cut_size: 1,
          cut_event_ids: ["ev-demo-007"],
          total_encoded_cut_cost: 100,
          total_estimated_collateral_minor_units: 0,
          is_cut_verified: true,
        },
      } as unknown as InvestigationAnalysisResponse;

      const elements = buildCytoscapeElements({
        events: DEMO_EVENTS,
        analysis: mockAnalysis,
      });

      const cutEdge = elements.find((el) => el.data.id === "ev-demo-007");
      assert.ok(cutEdge);
      assert.equal(cutEdge?.data.isCutEdge, true);
      assert.match(cutEdge?.classes || "", /cut-edge/);
    });
  });

  // ── 6. Missing Artifacts & Partial Analyses ────────────────────────────────
  describe("Missing Artifacts, Insufficient Evidence & Feasibility", () => {
    it("handles missing risk model artifact without fabricated values", () => {
      const responseWithoutML = {
        case_id: "case-001",
        simulation_timestamp: "2026-10-09T08:00:00Z",
        analysis_timestamp: "2026-10-09T08:01:00Z",
        overall_status: "partial",
        stages: {
          risk_assessment: {
            status: "unavailable",
            message: "Mule risk model artifact unavailable. No risk scores fabricated.",
            details: {},
          },
        },
        risk_predictions: [],
      } as unknown as InvestigationAnalysisResponse;

      assert.equal(responseWithoutML.risk_predictions.length, 0);
      assert.equal(responseWithoutML.stages.risk_assessment.status, "unavailable");
    });

    it("handles insufficient forecast evidence correctly", () => {
      const responseInsufficientEvidence = {
        case_id: "case-001",
        overall_status: "partial",
        stages: {
          forecast_simulation: {
            status: "insufficient_evidence",
            message: "No plausible future trajectories identified within forecast horizon.",
          },
        },
        forecast_report: {
          status: "insufficient_evidence",
          paths_generated_count: 0,
          scenarios_evaluated_count: 0,
          paths: [],
        },
      } as unknown as InvestigationAnalysisResponse;

      assert.equal(responseInsufficientEvidence.forecast_report.paths_generated_count, 0);
      assert.equal(responseInsufficientEvidence.stages.forecast_simulation.status, "insufficient_evidence");
    });

    it("handles no eligible interventions when policy is infeasible", () => {
      const infeasibleResponse = {
        case_id: "case-001",
        overall_status: "partial",
        stages: {
          intervention_optimization: {
            status: "infeasible",
            message: "No candidates met hard policy constraints.",
          },
        },
        selected_recommendation: null,
        evaluated_candidates: {
          total_candidates_count: 5,
          feasible_candidates_count: 0,
          infeasible_candidates_count: 5,
          pareto_frontier_size: 0,
        },
      } as unknown as InvestigationAnalysisResponse;

      assert.equal(infeasibleResponse.selected_recommendation, null);
      assert.equal(infeasibleResponse.evaluated_candidates.feasible_candidates_count, 0);
      assert.equal(infeasibleResponse.stages.intervention_optimization.status, "infeasible");
    });
  });
});
