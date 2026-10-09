export interface GraphNodeData {
  id: string;
  label: string;
  account_id: string;
  isTainted: boolean;
  taintedBalanceMinorUnits: number;
  isSeed: boolean;
  isSink: boolean;
  isCleanSource: boolean;
  riskScore?: number | null;
  riskLevel?: string | null;
  totalInflowMinorUnits: number;
  totalOutflowMinorUnits: number;
  transactionsCount: number;
}

export interface GraphEdgeData {
  id: string;
  source: string;
  target: string;
  amountMinorUnits: number;
  currency: string;
  occurredAt: string;
  isObserved: boolean;
  isCutEdge: boolean;
  isTaintAllocated: boolean;
  taintedAmountMinorUnits?: number;
  probability?: number | null;
  pathId?: string | null;
  status?: string;
  channel?: string;
  event_id?: string;
}

export type SelectedEntity =
  | { type: "node"; data: GraphNodeData }
  | { type: "edge"; data: GraphEdgeData }
  | null;

export interface GraphManifest {
  case_id: string;
  node_count: number;
  edge_count: number;
  nodes: string[];
  edges: Array<{
    event_id: string;
    source: string;
    target: string;
    amount_minor_units: number;
    currency: string;
    occurred_at: string;
    status: string;
  }>;
}
