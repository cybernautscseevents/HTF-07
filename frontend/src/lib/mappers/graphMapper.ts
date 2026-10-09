import type {
  TransactionEvent,
  InvestigationAnalysisResponse,
  GraphNodeData,
  GraphEdgeData,
} from "../../types/index.ts";

export interface CytoscapeElement {
  data: Record<string, unknown>;
  classes?: string;
}

export interface BuildGraphOptions {
  events: TransactionEvent[];
  analysis: InvestigationAnalysisResponse | null;
  decisionTimestamp?: string;
  showForecasts?: boolean;
  seedTxIds?: string[];
  sinkAccounts?: string[];
}

export function buildCytoscapeElements(
  options: BuildGraphOptions
): CytoscapeElement[] {
  const {
    events,
    analysis,
    decisionTimestamp,
    showForecasts = true,
    sinkAccounts = [],
  } = options;

  const decisionTime = decisionTimestamp
    ? new Date(decisionTimestamp).getTime()
    : Infinity;

  const nodeMap = new Map<string, GraphNodeData>();
  const edgeList: CytoscapeElement[] = [];

  const taintedAccountsSet = new Set(
    analysis?.taint_summary?.current_tainted_accounts || []
  );

  const riskMap = new Map<string, { score: number; level: string }>();
  if (analysis?.risk_predictions) {
    for (const rp of analysis.risk_predictions) {
      riskMap.set(rp.account_id, {
        score: rp.risk_score,
        level: rp.risk_level,
      });
    }
  }

  const cutEventIds = new Set(
    analysis?.chokepoint_report?.cut_event_ids || []
  );

  const sinkSet = new Set(sinkAccounts);

  // 1. Process observed events
  for (const ev of events) {
    const senderId = ev.sender.account_id;
    const receiverId = ev.receiver.account_id;
    const evTime = new Date(ev.occurred_at).getTime();
    const isAvailableAtT = evTime <= decisionTime;

    // Sender node
    if (!nodeMap.has(senderId)) {
      nodeMap.set(senderId, {
        id: senderId,
        label: senderId,
        account_id: senderId,
        isTainted: taintedAccountsSet.has(senderId),
        taintedBalanceMinorUnits: 0,
        isSeed: false,
        isSink: sinkSet.has(senderId),
        isCleanSource: false,
        totalInflowMinorUnits: 0,
        totalOutflowMinorUnits: 0,
        transactionsCount: 0,
      });
    }

    // Receiver node
    if (!nodeMap.has(receiverId)) {
      nodeMap.set(receiverId, {
        id: receiverId,
        label: receiverId,
        account_id: receiverId,
        isTainted: taintedAccountsSet.has(receiverId),
        taintedBalanceMinorUnits: 0,
        isSeed: false,
        isSink: sinkSet.has(receiverId),
        isCleanSource: false,
        totalInflowMinorUnits: 0,
        totalOutflowMinorUnits: 0,
        transactionsCount: 0,
      });
    }

    const sNode = nodeMap.get(senderId)!;
    const rNode = nodeMap.get(receiverId)!;

    sNode.totalOutflowMinorUnits += ev.amount_minor_units;
    sNode.transactionsCount += 1;
    rNode.totalInflowMinorUnits += ev.amount_minor_units;
    rNode.transactionsCount += 1;

    // Check if this is the first seed transaction
    if (analysis?.taint_summary) {
      // If receiver is in tainted accounts from seed
      if (taintedAccountsSet.has(receiverId)) {
        rNode.isTainted = true;
      }
    }

    const isCut = cutEventIds.has(ev.event_id);

    const edgeData: GraphEdgeData = {
      id: ev.event_id,
      source: senderId,
      target: receiverId,
      amountMinorUnits: ev.amount_minor_units,
      currency: ev.currency,
      occurredAt: ev.occurred_at,
      isObserved: true,
      isCutEdge: isCut,
      isTaintAllocated: false,
      probability: null,
      pathId: null,
      status: ev.status,
      channel: ev.channel,
      event_id: ev.event_id,
    };

    // Styling classes
    const classes = [
      "observed-edge",
      isAvailableAtT ? "historical" : "later-observation",
      isCut ? "cut-edge" : "",
    ]
      .filter(Boolean)
      .join(" ");

    edgeList.push({
      data: {
        ...edgeData,
        isAvailableAtT,
        label: `₹${(ev.amount_minor_units / 100).toLocaleString("en-IN")}`,
      },
      classes,
    });
  }

  // Detect seed node: sender of the seed transaction
  if (analysis) {
    for (const [acctId, node] of nodeMap.entries()) {
      if (riskMap.has(acctId)) {
        node.riskScore = riskMap.get(acctId)!.score;
        node.riskLevel = riskMap.get(acctId)!.level;
      }
      if (sinkSet.has(acctId)) {
        node.isSink = true;
      }
    }
  }

  // 2. Process forecast paths if enabled and available
  if (showForecasts && analysis?.forecast_report?.paths) {
    for (const path of analysis.forecast_report.paths) {
      for (let hopIdx = 0; hopIdx < path.hops.length; hopIdx++) {
        const hop = path.hops[hopIdx];
        const edgeId = `fc-${path.path_id}-hop-${hopIdx}`;

        // Ensure nodes exist
        if (!nodeMap.has(hop.from_account_id)) {
          nodeMap.set(hop.from_account_id, {
            id: hop.from_account_id,
            label: hop.from_account_id,
            account_id: hop.from_account_id,
            isTainted: taintedAccountsSet.has(hop.from_account_id),
            taintedBalanceMinorUnits: 0,
            isSeed: false,
            isSink: sinkSet.has(hop.from_account_id),
            isCleanSource: false,
            totalInflowMinorUnits: 0,
            totalOutflowMinorUnits: 0,
            transactionsCount: 0,
          });
        }

        if (!nodeMap.has(hop.to_account_id)) {
          nodeMap.set(hop.to_account_id, {
            id: hop.to_account_id,
            label: hop.to_account_id,
            account_id: hop.to_account_id,
            isTainted: false,
            taintedBalanceMinorUnits: 0,
            isSeed: false,
            isSink: sinkSet.has(hop.to_account_id),
            isCleanSource: false,
            totalInflowMinorUnits: 0,
            totalOutflowMinorUnits: 0,
            transactionsCount: 0,
          });
        }

        const edgeData: GraphEdgeData = {
          id: edgeId,
          source: hop.from_account_id,
          target: hop.to_account_id,
          amountMinorUnits: hop.amount_minor_units,
          currency: "INR",
          occurredAt: hop.occurred_at,
          isObserved: false,
          isCutEdge: false,
          isTaintAllocated: false,
          probability: hop.probability,
          pathId: path.path_id,
          status: "forecast",
        };

        edgeList.push({
          data: {
            ...edgeData,
            isForecast: true,
            label: `Forecast ${(hop.probability * 100).toFixed(0)}%`,
          },
          classes: "forecast-edge",
        });
      }
    }
  }

  // 3. Assemble Cytoscape nodes
  const nodeList: CytoscapeElement[] = [];
  for (const node of nodeMap.values()) {
    const classes = [
      "account-node",
      node.isTainted ? "tainted" : "clean",
      node.isSeed ? "seed" : "",
      node.isSink ? "sink" : "",
      node.riskLevel ? `risk-${node.riskLevel.toLowerCase()}` : "",
    ]
      .filter(Boolean)
      .join(" ");

    nodeList.push({
      data: {
        ...node,
      },
      classes,
    });
  }

  return [...nodeList, ...edgeList];
}
