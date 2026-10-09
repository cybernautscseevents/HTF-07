"use client";

import React, { useEffect, useRef, useState } from "react";
import cytoscape, { Core } from "cytoscape";
import {
  ZoomIn,
  ZoomOut,
  RotateCcw,
  Eye,
  EyeOff,
  GitBranch,
  Network,
} from "lucide-react";
import {
  TransactionEvent,
  InvestigationAnalysisResponse,
  SelectedEntity,
  GraphNodeData,
  GraphEdgeData,
} from "@/types";
import { buildCytoscapeElements } from "@/lib/mappers/graphMapper";
import { GraphLegend } from "./GraphLegend";
import { EntityInspector } from "./EntityInspector";

interface TransactionGraphProps {
  events: TransactionEvent[];
  analysis: InvestigationAnalysisResponse | null;
  decisionTimestamp: string;
  sinkAccounts?: string[];
  seedTxIds?: string[];
}

export function TransactionGraph({
  events,
  analysis,
  decisionTimestamp,
  sinkAccounts = [],
  seedTxIds = [],
}: TransactionGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  const [selectedEntity, setSelectedEntity] = useState<SelectedEntity>(null);
  const [showForecasts, setShowForecasts] = useState<boolean>(true);
  const [layoutType, setLayoutType] = useState<"breadthfirst" | "cose">("breadthfirst");

  useEffect(() => {
    if (!containerRef.current) return;

    const elements = buildCytoscapeElements({
      events,
      analysis,
      decisionTimestamp,
      showForecasts,
      sinkAccounts,
      seedTxIds,
    });

    if (cyRef.current) {
      cyRef.current.destroy();
    }

    const cy = cytoscape({
      container: containerRef.current,
      elements: elements as cytoscape.ElementDefinition[],
      style: [
        // ── Nodes ─────────────────────────────────────────────────────────
        {
          selector: "node",
          style: {
            label: "data(label)",
            color: "#f1f5f9",
            "font-size": "11px",
            "font-family": "ui-monospace, monospace",
            "font-weight": "bold",
            "text-valign": "bottom",
            "text-margin-y": 8,
            "background-color": "#17172b",
            "border-width": 2,
            "border-color": "#2e2e4a",
            width: 38,
            height: 38,
            "text-background-opacity": 0.94,
            "text-background-color": "#0c0c16",
            "text-background-padding": "3px 6px",
            "text-background-shape": "roundrectangle",
          },
        },
        {
          selector: "node.tainted",
          style: {
            "background-color": "#32141e",
            "border-color": "#e05263",
            "border-width": 2.5,
            color: "#fce4ec",
          },
        },
        {
          selector: "node.seed",
          style: {
            "background-color": "#3d1624",
            "border-color": "#e05263",
            "border-width": 3.5,
            width: 44,
            height: 44,
            color: "#fce4ec",
          },
        },
        {
          selector: "node.sink",
          style: {
            "background-color": "#1c1833",
            "border-color": "#b0baff",
            "border-width": 3,
            width: 44,
            height: 44,
            color: "#c9e8ff",
          },
        },
        {
          selector: "node:selected",
          style: {
            "border-color": "#6666ff",
            "border-width": 4,
          },
        },

        // ── Edges ─────────────────────────────────────────────────────────
        {
          selector: "edge",
          style: {
            width: 2.5,
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            "target-arrow-color": "#64748b",
            "line-color": "#64748b",
            "arrow-scale": 1.25,
            label: "data(label)",
            "font-size": "10px",
            "font-family": "ui-monospace, monospace",
            "font-weight": "bold",
            color: "#e2e8f0",
            "text-background-opacity": 0.94,
            "text-background-color": "#0c0c16",
            "text-background-padding": "3px 5px",
            "text-background-shape": "roundrectangle",
            "text-rotation": "none",
            "text-margin-y": -11,
          },
        },
        {
          selector: "edge.historical",
          style: {
            "line-color": "#64748b",
            "target-arrow-color": "#64748b",
            width: 2.5,
          },
        },
        {
          selector: "edge.later-observation",
          style: {
            "line-color": "#e5a84b",
            "target-arrow-color": "#e5a84b",
            opacity: 0.55,
            "line-style": "dotted",
            color: "#fed7aa",
          },
        },
        {
          selector: "edge.cut-edge",
          style: {
            "line-color": "#e05263",
            "target-arrow-color": "#e05263",
            width: 4,
            color: "#fca5a5",
            "font-weight": "bold",
          },
        },
        {
          selector: "edge.forecast-edge",
          style: {
            "line-style": "dashed",
            "line-dash-pattern": [6, 4],
            "line-color": "#b0baff",
            "target-arrow-color": "#b0baff",
            color: "#c9e8ff",
            width: 2.5,
          },
        },
        {
          selector: "edge:selected",
          style: {
            "line-color": "#6666ff",
            "target-arrow-color": "#6666ff",
            width: 4.5,
          },
        },
      ],
      layout: {
        name: layoutType,
        directed: true,
        padding: 40,
        animate: false,
        spacingFactor: 1.45,
      },
    });

    // Event listeners
    cy.on("tap", "node", (evt) => {
      const nodeData = evt.target.data() as GraphNodeData;
      setSelectedEntity({ type: "node", data: nodeData });
    });

    cy.on("tap", "edge", (evt) => {
      const edgeData = evt.target.data() as GraphEdgeData;
      setSelectedEntity({ type: "edge", data: edgeData });
    });

    cy.on("tap", (evt) => {
      if (evt.target === cy) {
        setSelectedEntity(null);
      }
    });

    cyRef.current = cy;

    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [events, analysis, decisionTimestamp, showForecasts, layoutType, sinkAccounts, seedTxIds]);

  const handleZoomIn = () => {
    if (cyRef.current) cyRef.current.zoom(cyRef.current.zoom() * 1.25);
  };

  const handleZoomOut = () => {
    if (cyRef.current) cyRef.current.zoom(cyRef.current.zoom() * 0.8);
  };

  const handleFit = () => {
    if (cyRef.current) cyRef.current.fit(undefined, 35);
  };

  const handleToggleLayout = () => {
    setLayoutType((prev) => (prev === "breadthfirst" ? "cose" : "breadthfirst"));
  };

  return (
    <div className="relative rounded-2xl border border-[#23233c] bg-[#0c0c16] overflow-hidden shadow-xl flex flex-col h-[580px] lg:h-[620px] font-sans">
      {/* Top Floating HUD Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 border-b border-[#23233c] bg-[#121222]/90 backdrop-blur-md z-20">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Network className="h-4 w-4 text-[#6666ff]" />
            <span className="text-xs font-bold text-white font-sans">
              Transaction flow graph
            </span>
          </div>
          {events.length > 0 && (
            <span className="text-xs text-slate-400 border-l border-[#23233c] pl-3 font-sans">
              {events.length} observed transfers
            </span>
          )}
          {analysis?.forecast_report?.paths && showForecasts && (
            <span className="text-xs text-[#b0baff] hidden sm:inline font-sans">
              • {analysis.forecast_report.paths.length} forecast trajectories active
            </span>
          )}
        </div>

        {/* HUD Controls */}
        <div className="flex items-center gap-2">
          {/* Toggle Forecast Edges */}
          <button
            onClick={() => setShowForecasts(!showForecasts)}
            className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-medium font-sans border transition-all cursor-pointer focus:outline-none focus:ring-1 focus:ring-[#6666ff] ${
              showForecasts
                ? "bg-[#6666ff]/15 text-[#c9e8ff] border-[#6666ff]/40 shadow-sm"
                : "bg-[#17172b] text-slate-400 border-[#23233c] hover:text-white"
            }`}
            title="Toggle display of simulated next-hop forecast trajectories"
          >
            {showForecasts ? <Eye className="h-3.5 w-3.5 text-[#b0baff]" /> : <EyeOff className="h-3.5 w-3.5" />}
            <span>Forecast trajectories</span>
          </button>

          {/* Toggle Layout */}
          <button
            onClick={handleToggleLayout}
            className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-[#17172b] hover:bg-[#20203a] text-slate-200 text-xs font-sans border border-[#23233c] transition-colors cursor-pointer focus:outline-none focus:ring-1 focus:ring-[#6666ff]"
            title={`Switch graph layout (current: ${layoutType === "breadthfirst" ? "Hierarchical flow" : "Force directed"})`}
          >
            <GitBranch className="h-3.5 w-3.5 text-[#b0baff]" />
            <span>{layoutType === "breadthfirst" ? "Hierarchical flow" : "Force directed"}</span>
          </button>

          {/* Zoom & Fit HUD */}
          <div className="flex items-center border-l border-[#23233c] pl-2 gap-1">
            <button
              onClick={handleZoomIn}
              className="p-1.5 rounded-lg bg-[#17172b] hover:bg-[#20203a] text-slate-300 hover:text-white transition-colors cursor-pointer border border-[#23233c]"
              title="Zoom in"
            >
              <ZoomIn className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={handleZoomOut}
              className="p-1.5 rounded-lg bg-[#17172b] hover:bg-[#20203a] text-slate-300 hover:text-white transition-colors cursor-pointer border border-[#23233c]"
              title="Zoom out"
            >
              <ZoomOut className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={handleFit}
              className="p-1.5 rounded-lg bg-[#17172b] hover:bg-[#20203a] text-slate-300 hover:text-white transition-colors cursor-pointer border border-[#23233c]"
              title="Fit to viewport / Center"
            >
              <RotateCcw className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Main Canvas Area */}
      <div className="relative flex-1 w-full h-full bg-graph-grid">
        <div ref={containerRef} className="absolute inset-0 w-full h-full" />

        {/* Empty state if no events */}
        {events.length === 0 && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-6 bg-[#0c0c16]/90 backdrop-blur-sm z-10 font-sans">
            <p className="text-sm font-semibold text-slate-300 font-sans">
              No transaction topology present
            </p>
            <p className="text-xs text-slate-400 mt-1 max-w-sm font-sans">
              Load a demo case from the top navigation to view the account graph and evaluate interventions.
            </p>
          </div>
        )}

        {/* Slide-over Entity Inspector Drawer */}
        <EntityInspector
          selectedEntity={selectedEntity}
          onClose={() => setSelectedEntity(null)}
        />
      </div>

      {/* Bottom Floating Legend Bar */}
      <div className="p-2 border-t border-[#23233c] bg-[#0c0c16]/95 backdrop-blur-md z-20">
        <GraphLegend />
      </div>
    </div>
  );
}

