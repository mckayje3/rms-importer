"use client";

import { useState, useEffect, useCallback } from "react";
import { sync } from "@/lib/api";
import type { FileJobStatus } from "@/types";

interface FileJobProgressProps {
  projectId: number;
  jobId: string;
  onComplete?: () => void;
}

export function FileJobProgress({
  projectId,
  jobId,
  onComplete,
}: FileJobProgressProps) {
  const [job, setJob] = useState<FileJobStatus | null>(null);
  const [error, setError] = useState<string>("");
  const [showErrors, setShowErrors] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const status = await sync.getFileJobStatus(projectId, jobId);
      setJob(status);

      if (status.status === "completed" || status.status === "failed") {
        onComplete?.();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to get job status");
    }
  }, [projectId, jobId, onComplete]);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(() => {
      fetchStatus();
    }, 5000);

    return () => clearInterval(interval);
  }, [fetchStatus]);

  // Stop polling when job is done
  useEffect(() => {
    if (job && (job.status === "completed" || job.status === "failed")) {
      // No need to keep polling
    }
  }, [job]);

  if (error) {
    return (
      <div className="rounded-md bg-red-50 border border-red-200 p-3 text-sm text-red-700">
        {error}
      </div>
    );
  }

  if (!job) {
    return (
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        Loading job status...
      </div>
    );
  }

  const isRunning = job.status === "queued" || job.status === "running";
  const isComplete = job.status === "completed";
  const isFailed = job.status === "failed";
  const progress = job.total_files > 0
    ? Math.round((job.uploaded_files / job.total_files) * 100)
    : 0;

  return (
    <div className="rounded-md border border-purple-200 bg-purple-50 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium text-purple-800">
          {isRunning && "Uploading files to Procore..."}
          {isComplete && "File upload complete"}
          {isFailed && "File upload failed"}
        </h4>
        {isRunning && (
          <span className="text-xs text-purple-600">
            You can navigate away — this will continue in the background
          </span>
        )}
      </div>

      {/* Progress bar */}
      <div className="w-full bg-purple-200 rounded-full h-2">
        <div
          className={`h-2 rounded-full transition-all duration-500 ${
            isComplete
              ? "bg-green-500"
              : isFailed
                ? "bg-red-500"
                : "bg-purple-600"
          }`}
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* Progress text */}
      <div className="flex items-center justify-between text-sm">
        <span className={isComplete ? "text-green-700" : isFailed ? "text-red-700" : "text-purple-700"}>
          {job.uploaded_files} / {job.total_files} files uploaded
        </span>
        {isRunning && (
          <span className="flex items-center gap-1 text-purple-500">
            <svg className="animate-spin h-3 w-3" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            {progress}%
          </span>
        )}
      </div>

      {/* Errors */}
      {job.errors.length > 0 && (
        <div>
          <button
            type="button"
            onClick={() => setShowErrors(!showErrors)}
            className="text-xs text-red-600 hover:text-red-800"
          >
            {showErrors ? "Hide" : "Show"} {job.errors.length} error{job.errors.length !== 1 ? "s" : ""}
          </button>
          {showErrors && (
            <ul className="mt-1 max-h-32 overflow-y-auto text-xs text-red-600 space-y-0.5">
              {job.errors.map((err, i) => (
                <li key={i} className="truncate">
                  {err}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Completion summary */}
      {isComplete && job.result_summary && (
        <div className="text-sm text-green-700 bg-green-50 rounded p-2">
          Successfully uploaded {job.result_summary.uploaded} of {job.result_summary.total} files
          {job.result_summary.errors > 0 && ` (${job.result_summary.errors} errors)`}
        </div>
      )}
    </div>
  );
}
