"use client";

import { useState, useEffect, useRef } from "react";
import { dailyLogs } from "@/lib/api";
import type { DailyLogSyncPlan, DailyLogJobStatus, DailyLogAnalyzeResponse } from "@/types";

interface DailyLogReviewProps {
  analysis: DailyLogAnalyzeResponse;
  projectId: number;
  sessionId: string;
  companyId: number;
  onComplete: (result: {
    equipment: number;
    labor: number;
    narratives: number;
    errors: string[];
  }) => void;
  onCancel: () => void;
}

export function DailyLogReview({
  analysis,
  projectId,
  sessionId,
  companyId,
  onComplete,
  onCancel,
}: DailyLogReviewProps) {
  const { plan, vendor_map } = analysis;

  const [applyEquipment, setApplyEquipment] = useState(true);
  const [applyLabor, setApplyLabor] = useState(true);
  const [applyNarratives, setApplyNarratives] = useState(true);
  const [executing, setExecuting] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<DailyLogJobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  // Poll job status
  useEffect(() => {
    if (!jobId) return;

    const poll = async () => {
      try {
        const status = await dailyLogs.getJobStatus(jobId);
        setJobStatus(status);

        if (status.status === "completed" || status.status === "failed") {
          if (pollRef.current) clearInterval(pollRef.current);
          onCompleteRef.current({
            equipment: status.equipment_created,
            labor: status.labor_created,
            narratives: status.narratives_created,
            errors: status.errors,
          });
        }
      } catch {
        // Ignore poll errors
      }
    };

    poll();
    pollRef.current = setInterval(poll, 3000);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [jobId]);

  const handleExecute = async () => {
    setExecuting(true);
    setError(null);

    try {
      const result = await dailyLogs.execute(projectId, sessionId, companyId, {
        equipment: applyEquipment,
        labor: applyLabor,
        narratives: applyNarratives,
        vendorMap: vendor_map,
      });

      if (result.job_id) {
        setJobId(result.job_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
      setExecuting(false);
    }
  };

  const nothingSelected = !applyEquipment && !applyLabor && !applyNarratives;

  // Progress view
  if (jobId && jobStatus) {
    const progress = jobStatus.total > 0
      ? Math.round((jobStatus.completed / jobStatus.total) * 100)
      : 0;

    return (
      <div className="space-y-6">
        <div className="text-center py-4">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-orange-500 mx-auto mb-4"></div>
          <p className="text-gray-700 font-medium">Importing daily logs to Procore...</p>
          <p className="text-sm text-gray-500 mt-1">
            {jobStatus.equipment_created > 0 && `${jobStatus.equipment_created} equipment`}
            {jobStatus.labor_created > 0 && `${jobStatus.equipment_created > 0 ? ", " : ""}${jobStatus.labor_created} labor`}
            {jobStatus.narratives_created > 0 && `${(jobStatus.equipment_created > 0 || jobStatus.labor_created > 0) ? ", " : ""}${jobStatus.narratives_created} narratives`}
            {jobStatus.errors.length > 0 && ` (${jobStatus.errors.length} errors)`}
          </p>
        </div>

        <div className="w-full bg-gray-200 rounded-full h-2">
          <div
            className="bg-orange-500 h-2 rounded-full transition-all duration-500"
            style={{ width: `${Math.min(progress, 100)}%` }}
          />
        </div>
        <p className="text-xs text-gray-500 text-center">{progress}%</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="bg-gray-50 rounded-lg p-4">
        <p className="text-sm text-gray-700">{plan.summary}</p>
      </div>

      {/* Breakdown */}
      <div className="grid grid-cols-3 gap-4">
        {plan.equipment_creates > 0 && (
          <div className="bg-blue-50 rounded-lg p-3 text-center">
            <p className="text-2xl font-bold text-blue-600">{plan.equipment_creates}</p>
            <p className="text-xs text-blue-500">Equipment</p>
          </div>
        )}
        {plan.labor_creates > 0 && (
          <div className="bg-green-50 rounded-lg p-3 text-center">
            <p className="text-2xl font-bold text-green-600">{plan.labor_creates}</p>
            <p className="text-xs text-green-500">Labor</p>
          </div>
        )}
        {plan.narrative_creates > 0 && (
          <div className="bg-purple-50 rounded-lg p-3 text-center">
            <p className="text-2xl font-bold text-purple-600">{plan.narrative_creates}</p>
            <p className="text-xs text-purple-500">Narratives</p>
          </div>
        )}
      </div>

      {/* Unmatched vendors warning */}
      {plan.unmatched_vendors.length > 0 && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3">
          <p className="text-sm font-medium text-yellow-800 mb-1">
            {plan.unmatched_vendors.length} employer{plan.unmatched_vendors.length !== 1 ? "s" : ""} not matched to Procore vendors
          </p>
          <p className="text-xs text-yellow-600 mb-2">
            Labor entries for these employers will be created without a vendor link.
          </p>
          <ul className="text-xs text-yellow-700 space-y-0.5">
            {plan.unmatched_vendors.map((v) => (
              <li key={v}>{v}</li>
            ))}
          </ul>
        </div>
      )}

      {/* No changes */}
      {!plan.has_changes && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-center">
          <p className="text-sm text-blue-700 font-medium">No entries to import.</p>
        </div>
      )}

      {/* Options */}
      {plan.has_changes && (
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-gray-700">Options</h3>
          {plan.equipment_creates > 0 && (
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={applyEquipment}
                onChange={(e) => setApplyEquipment(e.target.checked)}
                className="rounded border-gray-300 text-orange-500 focus:ring-orange-500"
              />
              <span className="text-sm text-gray-700">
                Import {plan.equipment_creates} equipment entr{plan.equipment_creates !== 1 ? "ies" : "y"}
              </span>
            </label>
          )}
          {plan.labor_creates > 0 && (
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={applyLabor}
                onChange={(e) => setApplyLabor(e.target.checked)}
                className="rounded border-gray-300 text-orange-500 focus:ring-orange-500"
              />
              <span className="text-sm text-gray-700">
                Import {plan.labor_creates} labor entr{plan.labor_creates !== 1 ? "ies" : "y"}
              </span>
            </label>
          )}
          {plan.narrative_creates > 0 && (
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={applyNarratives}
                onChange={(e) => setApplyNarratives(e.target.checked)}
                className="rounded border-gray-300 text-orange-500 focus:ring-orange-500"
              />
              <span className="text-sm text-gray-700">
                Import {plan.narrative_creates} narrative entr{plan.narrative_creates !== 1 ? "ies" : "y"}
              </span>
            </label>
          )}
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-4">
        <button
          onClick={onCancel}
          className="flex-1 py-3 px-4 rounded-lg font-medium border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors"
        >
          Back
        </button>
        {plan.has_changes && (
          <button
            onClick={handleExecute}
            disabled={executing || nothingSelected}
            className="flex-1 py-3 px-4 rounded-lg font-medium bg-orange-500 text-white hover:bg-orange-600 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {executing ? (
              <>
                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
                Starting...
              </>
            ) : (
              "Import to Procore"
            )}
          </button>
        )}
      </div>
    </div>
  );
}
