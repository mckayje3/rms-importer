"use client";

import { useState, useEffect, useRef } from "react";
import { observations } from "@/lib/api";
import type { ObservationsAnalyzeResponse, ObservationsJobStatus } from "@/types";

interface ObservationsReviewProps {
  analysis: ObservationsAnalyzeResponse;
  projectId: number;
  sessionId: string;
  companyId: number;
  onComplete: (result: {
    observations_created: number;
    locations_created: number;
    errors: string[];
  }) => void;
  onCancel: () => void;
}

export function ObservationsReview({
  analysis,
  projectId,
  sessionId,
  companyId,
  onComplete,
  onCancel,
}: ObservationsReviewProps) {
  const { plan, location_map } = analysis;

  const [createLocations, setCreateLocations] = useState(true);
  const [selectedTypeId, setSelectedTypeId] = useState<number | null>(null);
  const [executing, setExecuting] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<ObservationsJobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  // Poll job status
  useEffect(() => {
    if (!jobId) return;

    const poll = async () => {
      try {
        const status = await observations.getJobStatus(jobId);
        setJobStatus(status);

        if (status.status === "completed" || status.status === "failed") {
          if (pollRef.current) clearInterval(pollRef.current);
          onCompleteRef.current({
            observations_created: status.observations_created,
            locations_created: status.locations_created,
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
      const result = await observations.execute(projectId, sessionId, companyId, {
        observationTypeId: selectedTypeId,
        createLocations,
        locationMap: location_map,
      });

      if (result.job_id) {
        setJobId(result.job_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
      setExecuting(false);
    }
  };

  // Progress view
  if (jobId && jobStatus) {
    const progress = jobStatus.total > 0
      ? Math.round((jobStatus.completed / jobStatus.total) * 100)
      : 0;

    return (
      <div className="space-y-6">
        <div className="text-center py-4">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-orange-500 mx-auto mb-4"></div>
          <p className="text-gray-700 font-medium">Importing observations to Procore...</p>
          <p className="text-sm text-gray-500 mt-1">
            {jobStatus.observations_created > 0 && `${jobStatus.observations_created} observations`}
            {jobStatus.locations_created > 0 && `${jobStatus.observations_created > 0 ? ", " : ""}${jobStatus.locations_created} locations`}
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
        <div className="bg-blue-50 rounded-lg p-3 text-center">
          <p className="text-2xl font-bold text-blue-600">{plan.creates}</p>
          <p className="text-xs text-blue-500">To Create</p>
        </div>
        <div className="bg-gray-50 rounded-lg p-3 text-center">
          <p className="text-2xl font-bold text-gray-600">{plan.already_exist}</p>
          <p className="text-xs text-gray-500">Already Exist</p>
        </div>
        <div className="bg-green-50 rounded-lg p-3 text-center">
          <p className="text-2xl font-bold text-green-600">{plan.total_rms}</p>
          <p className="text-xs text-green-500">Total in RMS</p>
        </div>
      </div>

      {/* Locations to create */}
      {plan.locations_to_create.length > 0 && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3">
          <p className="text-sm font-medium text-yellow-800 mb-1">
            {plan.locations_to_create.length} location{plan.locations_to_create.length !== 1 ? "s" : ""} not found in Procore
          </p>
          <ul className="text-xs text-yellow-700 space-y-0.5 mb-2">
            {plan.locations_to_create.map((loc) => (
              <li key={loc}>{loc}</li>
            ))}
          </ul>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={createLocations}
              onChange={(e) => setCreateLocations(e.target.checked)}
              className="rounded border-gray-300 text-orange-500 focus:ring-orange-500"
            />
            <span className="text-sm text-yellow-800">Create missing locations automatically</span>
          </label>
        </div>
      )}

      {/* Observation type selector */}
      {plan.observation_types.length > 0 && (
        <div className="space-y-2">
          <label className="block text-sm font-medium text-gray-700">
            Observation Type
          </label>
          <select
            value={selectedTypeId ?? ""}
            onChange={(e) => setSelectedTypeId(e.target.value ? Number(e.target.value) : null)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-orange-500 focus:ring-orange-500"
          >
            <option value="">Select a type (required)...</option>
            {plan.observation_types.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}{t.category ? ` (${t.category})` : ""}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* No changes */}
      {!plan.has_changes && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-center">
          <p className="text-sm text-blue-700 font-medium">All deficiencies already exist in Procore.</p>
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
            disabled={executing || !selectedTypeId}
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
