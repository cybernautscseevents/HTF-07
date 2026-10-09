"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  Zap,
  AlertTriangle,
  Scale,
  Brain,
  FileText,
  GitFork,
  Target,
  ArrowRight,
  Search,
} from "lucide-react";
import {
  FraudCase,
  TransactionEvent,
  InvestigationAnalysisResponse,
  InvestigationAnalysisRequest,
} from "@/types";
import { apiClient, ApiError } from "@/lib/api/client";
import {
  loadDemoScenario,
  DEMO_DEFAULT_DECISION_TIME,
  getDemoAnalysisRequest,
} from "@/lib/demo/scenario";
import { Navbar } from "@/components/layout/Navbar";
import { InvestigationHeader } from "@/components/investigation/InvestigationHeader";
import { TimelineControl } from "@/components/timeline/TimelineControl";
import { TransactionGraph } from "@/components/graph/TransactionGraph";
import { ProvenancePanel } from "@/components/provenance/ProvenancePanel";
import { IntelligencePanel } from "@/components/intelligence/IntelligencePanel";
import { ChokepointPanel } from "@/components/chokepoint/ChokepointPanel";
import { RecommendationCard } from "@/components/interventions/RecommendationCard";
import { InterventionComparison } from "@/components/interventions/InterventionComparison";
import { EvidenceWarningsPanel } from "@/components/evidence/EvidenceWarningsPanel";
import { NewCaseModal } from "@/components/investigation/NewCaseModal";

type ActiveTab = "overview" | "comparison" | "provenance" | "intelligence" | "evidence";

export default function InvestigatorDashboard() {
  // State
  const [cases, setCases] = useState<FraudCase[]>([]);
  const [activeCaseId, setActiveCaseId] = useState<string>("");
  const [currentCase, setCurrentCase] = useState<FraudCase | null>(null);
  const [events, setEvents] = useState<TransactionEvent[]>([]);
  const [decisionTimestamp, setDecisionTimestamp] = useState<string>(DEMO_DEFAULT_DECISION_TIME);
  const [analysis, setAnalysis] = useState<InvestigationAnalysisResponse | null>(null);

  // Status & Loaders
  const [isBackendHealthy, setIsBackendHealthy] = useState<boolean>(true);
  const [isLoadingCases, setIsLoadingCases] = useState<boolean>(true);
  const [isLoadingTimeline, setIsLoadingTimeline] = useState<boolean>(false);
  const [isAnalyzing, setIsAnalyzing] = useState<boolean>(false);
  const [isLoadingDemo, setIsLoadingDemo] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ActiveTab>("overview");
  const [isNewCaseModalOpen, setIsNewCaseModalOpen] = useState<boolean>(false);

  // ── 1. Initial Health Check & Case Loading ─────────────────────────────────
  const fetchCases = useCallback(async () => {
    setIsLoadingCases(true);
    setErrorMessage(null);
    try {
      await apiClient.health();
      setIsBackendHealthy(true);

      const caseList = await apiClient.listCases();
      setCases(caseList);

      if (caseList.length > 0) {
        setActiveCaseId((prev) => prev || caseList[0].case_id);
      }
    } catch (err) {
      setIsBackendHealthy(false);
      setErrorMessage(
        err instanceof ApiError
          ? err.detail
          : "Could not connect to AEGIS-Flow backend server. Ensure FastAPI is running on http://localhost:8000."
      );
    } finally {
      setIsLoadingCases(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        await apiClient.health();
        if (!active) return;
        setIsBackendHealthy(true);

        const caseList = await apiClient.listCases();
        if (!active) return;
        setCases(caseList);

        if (caseList.length > 0) {
          setActiveCaseId((prev) => prev || caseList[0].case_id);
        }
      } catch (err) {
        if (!active) return;
        setIsBackendHealthy(false);
        setErrorMessage(
          err instanceof ApiError
            ? err.detail
            : "Could not connect to AEGIS-Flow backend server. Ensure FastAPI is running on http://localhost:8000."
        );
      } finally {
        if (active) setIsLoadingCases(false);
      }
    })();

    return () => {
      active = false;
    };
  }, []);

  // ── 2. Load Active Case Details & Events ───────────────────────────────────
  useEffect(() => {
    if (!activeCaseId) return;
    let active = true;

    void (async () => {
      try {
        setIsLoadingTimeline(true);
        const caseDetail = await apiClient.getCase(activeCaseId);
        if (!active) return;
        setCurrentCase(caseDetail);

        const timeline = await apiClient.getTimeline(activeCaseId);
        if (!active) return;
        setEvents(timeline);

        if (timeline.length > 0) {
          const midpointIdx = Math.min(2, timeline.length - 1);
          setDecisionTimestamp(timeline[midpointIdx].occurred_at);
        }
      } catch (err) {
        if (!active) return;
        setErrorMessage(
          err instanceof ApiError ? err.detail : "Failed to load case data"
        );
      } finally {
        if (active) setIsLoadingTimeline(false);
      }
    })();

    return () => {
      active = false;
    };
  }, [activeCaseId]);

  // ── 3. Run Analysis ────────────────────────────────────────────────────────
  const executeAnalysis = useCallback(async () => {
    if (!activeCaseId || events.length === 0) return;

    setIsAnalyzing(true);
    setErrorMessage(null);

    const seedEvent = events[0];
    const sinkCandidate = events[events.length - 1]?.receiver.account_id;

    const requestPayload: InvestigationAnalysisRequest = {
      simulation_timestamp: decisionTimestamp,
      taint_seeds: [
        {
          transaction_id: seedEvent.transaction_id,
          tainted_amount_minor_units: seedEvent.amount_minor_units,
        },
      ],
      source_account_ids: [seedEvent.receiver.account_id],
      sink_account_ids: sinkCandidate ? [sinkCandidate] : undefined,
      forecast_config: {
        top_k: 3,
        max_depth: 3,
        hop_delay_seconds: 300,
      },
      constraints: {
        minimum_required_illicit_recovery: 0,
        maximum_interventions: 2,
      },
    };

    try {
      const result = await apiClient.analyzeCase(activeCaseId, requestPayload);
      setAnalysis(result);
    } catch (err) {
      setErrorMessage(
        err instanceof ApiError
          ? err.detail
          : "Investigation analysis failed. No fabricated analysis returned."
      );
    } finally {
      setIsAnalyzing(false);
    }
  }, [activeCaseId, events, decisionTimestamp]);

  // ── 4. Load Demo Case Workflow ─────────────────────────────────────────────
  const handleLoadDemo = async () => {
    setIsLoadingDemo(true);
    setErrorMessage(null);
    try {
      const { case: demoCase } = await loadDemoScenario(apiClient);
      await fetchCases();
      setActiveCaseId(demoCase.case_id);
      setCurrentCase(demoCase);

      const timeline = await apiClient.getTimeline(demoCase.case_id);
      setEvents(timeline);
      setDecisionTimestamp(DEMO_DEFAULT_DECISION_TIME);

      const demoReq = getDemoAnalysisRequest(DEMO_DEFAULT_DECISION_TIME);
      const demoAnalysis = await apiClient.analyzeCase(demoCase.case_id, demoReq);
      setAnalysis(demoAnalysis);
    } catch (err) {
      setErrorMessage(
        err instanceof ApiError ? err.detail : "Failed to load demo scenario"
      );
    } finally {
      setIsLoadingDemo(false);
    }
  };

  // ── 5. Create Custom Case ──────────────────────────────────────────────────
  const handleCreateCase = async (newCase: FraudCase) => {
    const created = await apiClient.createCase(newCase);
    await fetchCases();
    setActiveCaseId(created.case_id);
  };

  return (
    <div className="min-h-screen bg-surface-base text-slate-100 flex flex-col font-sans selection:bg-brand-primary selection:text-white">
      {/* ── Layer A: Compact Command Header ── */}
      <Navbar
        cases={cases}
        activeCaseId={activeCaseId}
        onSelectCase={(id) => {
          setActiveCaseId(id);
          setAnalysis(null);
        }}
        onLoadDemo={handleLoadDemo}
        onNewCase={() => setIsNewCaseModalOpen(true)}
        isLoadingDemo={isLoadingDemo}
        isBackendHealthy={isBackendHealthy}
      />

      {/* ── Global Error Alert Banner ── */}
      {errorMessage && (
        <div className="bg-risk-danger/15 border-b border-risk-danger/30 px-4 py-2.5 text-xs text-rose-200 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-risk-danger shrink-0" />
            <span>{errorMessage}</span>
          </div>
          <button
            onClick={() => setErrorMessage(null)}
            className="text-xs text-rose-400 hover:text-white underline cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* ── Main Content Area ── */}
      <main className="flex-1 flex flex-col">
        {/* Layer B: Investigation Summary Banner */}
        <InvestigationHeader
          currentCase={currentCase}
          eventsCount={events.length}
          decisionTimestamp={decisionTimestamp}
          analysis={analysis}
          isAnalyzing={isAnalyzing || isLoadingTimeline}
          onRunAnalysis={executeAnalysis}
          reportedAmountMinorUnits={events[0]?.amount_minor_units}
        />

        {/* Empty State when no case exists */}
        {!currentCase && !isLoadingCases && (
          <div className="flex-1 flex flex-col items-center justify-center p-6 lg:p-12 text-center max-w-2xl mx-auto space-y-6">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-surface-elevated border border-surface-border text-brand-periwinkle shadow-xl">
              <Search className="h-7 w-7 text-brand-primary" />
            </div>

            <div className="space-y-3">
              <h2 className="text-xl font-semibold tracking-tight text-white">
                Investigate a reported payment
              </h2>
              <p className="text-sm text-slate-300 leading-relaxed max-w-lg mx-auto">
                Follow its movement across accounts, review the supporting evidence, and compare possible intervention points to intercept funds before they exit the banking network.
              </p>
            </div>

            {/* 3 Investigation Questions Guidance */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 w-full text-left pt-2">
              <div className="p-3.5 rounded-xl bg-surface-elevated border border-surface-border space-y-1">
                <span className="text-[11px] font-semibold text-brand-periwinkle uppercase tracking-wider block">
                  1. What happened?
                </span>
                <p className="text-xs text-slate-300">
                  Review the initial unauthorized transfer, reported fraud amount, and affected accounts.
                </p>
              </div>

              <div className="p-3.5 rounded-xl bg-surface-elevated border border-surface-border space-y-1">
                <span className="text-[11px] font-semibold text-brand-columbia uppercase tracking-wider block">
                  2. Where did it move?
                </span>
                <p className="text-xs text-slate-300">
                  Trace downstream transfers, multi-hop splits, and commingled funds on the timeline.
                </p>
              </div>

              <div className="p-3.5 rounded-xl bg-surface-elevated border border-surface-border space-y-1">
                <span className="text-[11px] font-semibold text-brand-celadon uppercase tracking-wider block">
                  3. What intervention to review?
                </span>
                <p className="text-xs text-slate-300">
                  Compare optimal hold options to maximize recovered funds while minimizing legitimate collateral.
                </p>
              </div>
            </div>

            <div className="pt-2">
              <button
                onClick={handleLoadDemo}
                disabled={isLoadingDemo}
                className="inline-flex items-center gap-2.5 rounded-lg bg-brand-primary px-5 py-3 text-sm font-medium text-white shadow-lg shadow-brand-primary/25 hover:bg-[#5252ee] transition-all cursor-pointer focus:outline-none focus:ring-2 focus:ring-brand-primary/50"
              >
                <Zap className="h-4 w-4" />
                <span>{isLoadingDemo ? "Loading scenario..." : "Load demo investigation (Operation Nightshade)"}</span>
                <ArrowRight className="h-4 w-4 text-brand-periwinkle" />
              </button>
            </div>
          </div>
        )}

        {/* Loaded Case Workspace */}
        {currentCase && (
          <div className="flex-1 p-4 lg:p-6 space-y-5 max-w-[1680px] w-full mx-auto">
            {/* Layer C: Transaction Network Graph (Dominant Workspace Centerpiece) */}
            <div className="w-full">
              <TransactionGraph
                events={events}
                analysis={analysis}
                decisionTimestamp={decisionTimestamp}
                sinkAccounts={analysis?.chokepoint_report ? ["Exit-CryptoDesk-909"] : []}
                seedTxIds={events[0] ? [events[0].transaction_id] : []}
              />
            </div>

            {/* Layer D: Investigation Timeline Scrubber */}
            <div className="w-full">
              <TimelineControl
                events={events}
                decisionTimestamp={decisionTimestamp}
                onSelectTimestamp={(ts) => {
                  setDecisionTimestamp(ts);
                }}
                analysisTimestamp={analysis?.simulation_timestamp}
              />
            </div>

            {/* Investigation Workbench Tabs Navigation */}
            <div className="border-b border-surface-border flex items-center gap-1 pt-2 overflow-x-auto">
              <button
                onClick={() => setActiveTab("overview")}
                className={`flex items-center gap-2 px-4 py-2.5 text-xs font-medium border-b-2 transition-all cursor-pointer whitespace-nowrap ${
                  activeTab === "overview"
                    ? "border-brand-primary text-white bg-surface-elevated/80 font-semibold"
                    : "border-transparent text-slate-400 hover:text-slate-200 hover:bg-surface-elevated/40"
                }`}
              >
                <Target className={`h-3.5 w-3.5 ${activeTab === "overview" ? "text-brand-primary" : "text-slate-400"}`} />
                <span>Recommended intervention</span>
              </button>

              <button
                onClick={() => setActiveTab("comparison")}
                className={`flex items-center gap-2 px-4 py-2.5 text-xs font-medium border-b-2 transition-all cursor-pointer whitespace-nowrap ${
                  activeTab === "comparison"
                    ? "border-brand-primary text-white bg-surface-elevated/80 font-semibold"
                    : "border-transparent text-slate-400 hover:text-slate-200 hover:bg-surface-elevated/40"
                }`}
              >
                <Scale className={`h-3.5 w-3.5 ${activeTab === "comparison" ? "text-brand-periwinkle" : "text-slate-400"}`} />
                <span>Compare interventions ({analysis?.all_candidates?.length || 0})</span>
              </button>

              <button
                onClick={() => setActiveTab("provenance")}
                className={`flex items-center gap-2 px-4 py-2.5 text-xs font-medium border-b-2 transition-all cursor-pointer whitespace-nowrap ${
                  activeTab === "provenance"
                    ? "border-brand-primary text-white bg-surface-elevated/80 font-semibold"
                    : "border-transparent text-slate-400 hover:text-slate-200 hover:bg-surface-elevated/40"
                }`}
              >
                <GitFork className={`h-3.5 w-3.5 ${activeTab === "provenance" ? "text-brand-columbia" : "text-slate-400"}`} />
                <span>Money trail</span>
              </button>

              <button
                onClick={() => setActiveTab("intelligence")}
                className={`flex items-center gap-2 px-4 py-2.5 text-xs font-medium border-b-2 transition-all cursor-pointer whitespace-nowrap ${
                  activeTab === "intelligence"
                    ? "border-brand-primary text-white bg-surface-elevated/80 font-semibold"
                    : "border-transparent text-slate-400 hover:text-slate-200 hover:bg-surface-elevated/40"
                }`}
              >
                <Brain className={`h-3.5 w-3.5 ${activeTab === "intelligence" ? "text-brand-periwinkle" : "text-slate-400"}`} />
                <span>Predictions and risk signals</span>
              </button>

              <button
                onClick={() => setActiveTab("evidence")}
                className={`flex items-center gap-2 px-4 py-2.5 text-xs font-medium border-b-2 transition-all cursor-pointer whitespace-nowrap ${
                  activeTab === "evidence"
                    ? "border-brand-primary text-white bg-surface-elevated/80 font-semibold"
                    : "border-transparent text-slate-400 hover:text-slate-200 hover:bg-surface-elevated/40"
                }`}
              >
                <FileText className={`h-3.5 w-3.5 ${activeTab === "evidence" ? "text-slate-300" : "text-slate-400"}`} />
                <span>Evidence and limitations</span>
              </button>
            </div>

            {/* Workbench Tab Panes */}
            <div className="pt-1">
              {activeTab === "overview" && (
                <div className="space-y-4">
                  {/* Hero: Selected Pareto Recommendation Card */}
                  <RecommendationCard
                    recommendation={analysis?.selected_recommendation || null}
                    decisionTimestamp={decisionTimestamp}
                  />

                  {/* Chokepoint & Min-Cut Barrier Panel */}
                  <ChokepointPanel
                    chokepointReport={analysis?.chokepoint_report || null}
                    selectedRecommendation={analysis?.selected_recommendation || null}
                    sourceAccounts={events[0] ? [events[0].receiver.account_id] : []}
                    sinkAccounts={["Exit-CryptoDesk-909"]}
                  />
                </div>
              )}

              {activeTab === "comparison" && (
                <InterventionComparison
                  candidates={analysis?.all_candidates || []}
                  competingReasons={analysis?.competing_candidates || []}
                  selectedInterventionId={
                    analysis?.selected_recommendation?.intervention_id
                  }
                  summary={analysis?.evaluated_candidates}
                />
              )}

              {activeTab === "provenance" && (
                <ProvenancePanel
                  taintSummary={analysis?.taint_summary || null}
                  selectedRecommendationIntercepted={
                    analysis?.selected_recommendation?.modeled_tainted_capital_intercepted
                  }
                />
              )}

              {activeTab === "intelligence" && (
                <IntelligencePanel
                  riskPredictions={analysis?.risk_predictions || []}
                  nextHopPredictions={analysis?.next_hop_predictions || []}
                  forecastReport={analysis?.forecast_report || null}
                  riskStage={analysis?.stages?.risk_assessment}
                  nextHopStage={analysis?.stages?.next_hop_prediction}
                  forecastStage={analysis?.stages?.forecast_simulation}
                />
              )}

              {activeTab === "evidence" && (
                <EvidenceWarningsPanel
                  warnings={analysis?.warnings_and_limitations || []}
                  stages={analysis?.stages}
                  analysisTimestamp={analysis?.analysis_timestamp}
                  overallStatus={analysis?.overall_status}
                />
              )}
            </div>
          </div>
        )}
      </main>

      {/* ── New Case Modal ── */}
      <NewCaseModal
        isOpen={isNewCaseModalOpen}
        onClose={() => setIsNewCaseModalOpen(false)}
        onCreateCase={handleCreateCase}
      />
    </div>
  );
}
