"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { sync } from "@/lib/api";
import type { FileJobStatus } from "@/types";

interface FileJobProgressProps {
  projectId: number;
  jobId: string;
  label?: string;
  onComplete?: () => void;
}

const MAX_CONSECUTIVE_ERRORS = 5;

export function FileJobProgress({
  projectId,
  jobId,
  label = "files",
  onComplete,
}: FileJobProgressProps) {
  const [job, setJob] = useState<FileJobStatus | null>(null);
  const [error, setError] = useState<string>("");
  const [showErrors, setShowErrors] = useState(false);
  const [connectionWarning, setConnectionWarning] = useState(false);
  const consecutiveErrors = useRef(0);
  const isDone = useRef(false);

  const fetchStatus = useCallback(async () => {
    if (isDone.current) return;

    try {
      const status = await sync.getFileJobStatus(projectId, jobId);
      setJob(status);
      consecutiveErrors.current = 0;
      setConnectionWarning(false);

      if (status.status === "completed" || status.status === "failed") {
        isDone.current = true;
        onComplete?.();
      }
    } catch (err) {
      consecutiveErrors.current += 1;

      if (consecutiveErrors.current >= MAX_CONSECUTIVE_ERRORS) {
        // Too many failures — show error
        setError(
          "Lost connection to server. The sync is still running — " +
          "refresh the page to check progress."
        );
      } else {
        // Transient — show warning but keep polling
        setConnectionWarning(true);
      }
    }
  }, [projectId, jobId, onComplete]);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  if (error) {
    return (
      <div className="rounded-md bg-yellow-50 border border-yellow-200 p-4 space-y-2">
        <p className="text-sm text-yellow-800">{error}</p>
        {job && (
          <p className="text-xs text-yellow-600">
            Last seen: {job.uploaded_files} / {job.total_files} completed
          </p>
        )}
        <button
          type="button"
          onClick={() => {
            setError("");
            consecutiveErrors.current = 0;
            fetchStatus();
          }}
          className="text-xs font-medium text-yellow-700 hover:text-yellow-900 underline"
        >
          Retry connection
        </button>
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
          {isRunning && `Syncing ${label} to Procore...`}
          {isComplete && "Sync complete"}
          {isFailed && "Sync failed"}
        </h4>
        {isRunning && (
          <span className="text-xs text-purple-600">
            You can navigate away — this will continue in the background
          </span>
        )}
      </div>

      {/* Connection warning */}
      {connectionWarning && isRunning && (
        <p className="text-xs text-yellow-600">
          Connection interrupted — retrying...
        </p>
      )}

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
          {job.uploaded_files} / {job.total_files} {label} synced
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
          {job.result_summary.created != null && `${job.result_summary.created} created`}
          {job.result_summary.updated != null && `, ${job.result_summary.updated} updated`}
          {job.result_summary.files != null && job.result_summary.files > 0 && `, ${job.result_summary.files} files`}
          {job.result_summary.errors > 0 && ` (${job.result_summary.errors} errors)`}
        </div>
      )}
    </div>
  );
}
