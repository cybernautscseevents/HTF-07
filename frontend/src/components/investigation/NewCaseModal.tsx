"use client";

import React, { useState } from "react";
import { X, FolderPlus } from "lucide-react";
import { FraudCase, CaseOrigin, CaseStatus } from "@/types";

interface NewCaseModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreateCase: (newCase: FraudCase) => Promise<void>;
}

export function NewCaseModal({
  isOpen,
  onClose,
  onCreateCase,
}: NewCaseModalProps) {
  const [caseId, setCaseId] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [origin, setOrigin] = useState<CaseOrigin>("customer_report");
  const [status, setStatus] = useState<CaseStatus>("open");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!caseId.trim() || !title.trim()) {
      setError("Case ID and Title are required.");
      return;
    }

    setIsSubmitting(true);
    setError(null);

    const now = new Date().toISOString();
    const caseData: FraudCase = {
      schema_version: "1.0.0",
      case_id: caseId.trim(),
      title: title.trim(),
      description: description.trim() || null,
      origin,
      status,
      transaction_ids: [],
      opened_at: now,
      updated_at: now,
    };

    try {
      await onCreateCase(caseData);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create case");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 font-sans">
      <div className="w-full max-w-md rounded-xl border border-surface-border bg-surface-elevated p-5 shadow-2xl space-y-4">
        <div className="flex items-center justify-between pb-3 border-b border-surface-border">
          <div className="flex items-center gap-2">
            <FolderPlus className="h-4 w-4 text-brand-periwinkle" />
            <h3 className="text-sm font-semibold text-white tracking-wide">
              Create new investigation case
            </h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-slate-400 hover:text-white hover:bg-surface-raised transition-colors cursor-pointer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {error && (
          <div className="p-2.5 rounded-lg bg-risk-danger/15 border border-risk-danger/30 text-xs text-rose-300">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-3.5 text-xs">
          <div>
            <label className="block text-slate-300 text-xs font-medium mb-1">
              Case identifier <span className="text-rose-400">*</span>
            </label>
            <input
              type="text"
              value={caseId}
              onChange={(e) => setCaseId(e.target.value)}
              placeholder="e.g. case-2026-ops-042"
              className="w-full rounded-lg bg-surface-card border border-surface-border px-3 py-2 text-white font-mono placeholder:text-slate-500 focus:border-brand-primary outline-none transition-colors"
              required
            />
          </div>

          <div>
            <label className="block text-slate-300 text-xs font-medium mb-1">
              Investigation title <span className="text-rose-400">*</span>
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. UPI Rapid Dispersal Network Alpha"
              className="w-full rounded-lg bg-surface-card border border-surface-border px-3 py-2 text-white placeholder:text-slate-500 focus:border-brand-primary outline-none transition-colors"
              required
            />
          </div>

          <div>
            <label className="block text-slate-300 text-xs font-medium mb-1">
              Description / investigative notes
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Case background, reporting bank, initial suspicious transaction references..."
              rows={3}
              className="w-full rounded-lg bg-surface-card border border-surface-border px-3 py-2 text-white placeholder:text-slate-500 focus:border-brand-primary outline-none resize-none transition-colors"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-slate-300 text-xs font-medium mb-1">Origin</label>
              <select
                value={origin}
                onChange={(e) => setOrigin(e.target.value as CaseOrigin)}
                className="w-full rounded-lg bg-surface-card border border-surface-border px-3 py-2 text-white focus:border-brand-primary outline-none text-xs transition-colors"
              >
                <option value="customer_report">Customer Report</option>
                <option value="bank_detection">Bank Detection</option>
                <option value="intelligence_feed">Intelligence Feed</option>
                <option value="law_enforcement">Law Enforcement</option>
                <option value="synthetic">Synthetic</option>
              </select>
            </div>

            <div>
              <label className="block text-slate-300 text-xs font-medium mb-1">Status</label>
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value as CaseStatus)}
                className="w-full rounded-lg bg-surface-card border border-surface-border px-3 py-2 text-white focus:border-brand-primary outline-none text-xs transition-colors"
              >
                <option value="open">Open</option>
                <option value="under_investigation">Under Investigation</option>
                <option value="escalated">Escalated</option>
              </select>
            </div>
          </div>

          <div className="flex items-center justify-end gap-2 pt-3 border-t border-surface-border">
            <button
              type="button"
              onClick={onClose}
              className="px-3.5 py-1.5 rounded-lg bg-surface-raised hover:bg-surface-card text-slate-300 transition-colors cursor-pointer border border-surface-border text-xs"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-4 py-1.5 rounded-lg bg-brand-primary hover:bg-[#5252ee] text-white font-medium transition-colors cursor-pointer disabled:opacity-50 text-xs shadow-sm"
            >
              {isSubmitting ? "Creating..." : "Create Case"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
