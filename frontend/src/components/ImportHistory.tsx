"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { sync } from "@/lib/api";
import type { FileJobStatus, JobType } from "@/types";

const MODULE_LABELS: Record<JobType, string> = {
  submittals: "Submittals",
  rfi: "RFIs",
  daily_logs: "Daily Logs",
  observations: "Observations",
};

// Backend writes naive UTC timestamps — append Z so JS doesn't read them as local.
function formatRelativeTime(iso: string | null): string {
  if (!iso) return "";
  const withTz = /Z$|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + "Z";
  const then = new Date(withTz);
  if (isNaN(then.getTime())) return "";
  const diffSec = Math.max(0, Math.floor((Date.now() - then.getTime()) / 1000));
  if (diffSec < 60) return "just now";
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  if (diffSec < 604800) return `${Math.floor(diffSec / 86400)}d ago`;
  return then.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function moduleLabel(job: FileJobStatus): string {
  if (job.job_type) return MODULE_LABELS[job.job_type];
  // Pre-job_type rows: best-effort inference from result_summary shape.
  const s = job.result_summary;
  if (s && s.uploaded != null && s.created == null && s.updated == null) {
    return "File upload";
  }
  return "Import";
}

function jobDetail(job: FileJobStatus): string {
  const s = job.result_summary;
  if (!s) {
    return `${job.uploaded_files} / ${job.total_files} processed`;
  }
  const parts: string[] = [];
  if (s.created != null) parts.push(`${s.created} created`);
  if (s.updated != null) parts.push(`${s.updated} updated`);
  if (s.files != null && s.files > 0) parts.push(`${s.files} files`);
  if (parts.length === 0 && s.uploaded != null) {
    parts.push(`${s.uploaded} of ${s.total} processed`);
  }
  return parts.join(", ") || "No changes";
}

function statusBadge(status: FileJobStatus["status"]) {
  switch (status) {
    case "completed":
      return { color: "text-green-700 bg-green-100", label: "Completed" };
    case "failed":
      return { color: "text-red-700 bg-red-100", label: "Failed" };
    case "running":
      return { color: "text-blue-700 bg-blue-100", label: "Running" };
    case "queued":
      return { color: "text-blue-700 bg-blue-100", label: "Queued" };
    default:
      return { color: "text-gray-700 bg-gray-100", label: status };
  }
}

interface ImportHistoryProps {
  projectId: number;
  limit?: number;
  // Called when the user clicks an in-progress job. The parent can route
  // back to the live-progress view. If omitted, the row is non-interactive.
  onResumeJob?: (job: FileJobStatus) => void;
  // Default to expanded list when there are multiple jobs.
  defaultExpanded?: boolean;
}

export function ImportHistory({
  projectId,
  limit = 10,
  onResumeJob,
  defaultExpanded = false,
}: ImportHistoryProps) {
  const [jobs, setJobs] = useState<FileJobStatus[] | null>(null);
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [now, setNow] = useState(Date.now());

  const fetchJobs = useCallback(async () => {
    try {
      const result = await sync.listJobs(projectId, limit);
      setJobs(result.jobs);
    } catch {
      // Non-fatal — leave previous state in place
    }
  }, [projectId, limit]);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  // Re-poll while any job is still active so the banner reflects live state.
  const hasActive = useMemo(
    () => (jobs ?? []).some((j) => j.status === "queued" || j.status === "running"),
    [jobs]
  );

  useEffect(() => {
    if (!hasActive) return;
    const id = setInterval(fetchJobs, 5000);
    return () => clearInterval(id);
  }, [hasActive, fetchJobs]);

  // Re-render once a minute so "5m ago" stays fresh without re-fetching.
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);

  if (jobs === null) {
    return null; // First load — stay quiet rather than flash a loader
  }

  if (jobs.length === 0) {
    return null;
  }

  const latest = jobs[0];
  const badge = statusBadge(latest.status);
  const errorCount =
    latest.result_summary?.errors ?? latest.errors.length ?? 0;
  const timestamp = formatRelativeTime(
    latest.completed_at ?? latest.started_at ?? latest.created_at
  );
  // Keep `now` referenced so the lint rule doesn't strip the interval above.
  void now;

  const canResume =
    onResumeJob && (latest.status === "queued" || latest.status === "running");

  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <button
        type="button"
        onClick={() => {
          if (canResume) {
            onResumeJob!(latest);
          } else if (jobs.length > 1) {
            setExpanded((v) => !v);
          }
        }}
        className={`w-full text-left px-4 py-3 flex items-center justify-between gap-3 ${
          canResume || jobs.length > 1 ? "hover:bg-gray-50" : "cursor-default"
        }`}
      >
        <div className="flex items-center gap-3 min-w-0">
          <span
            className={`text-xs font-medium px-2 py-0.5 rounded-full ${badge.color}`}
          >
            {badge.label}
          </span>
          <span className="text-sm text-gray-900 truncate">
            <span className="font-medium">{moduleLabel(latest)}</span>
            <span className="text-gray-500"> · {jobDetail(latest)}</span>
            {errorCount > 0 && (
              <span className="text-red-600"> · {errorCount} error{errorCount !== 1 ? "s" : ""}</span>
            )}
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0 text-xs text-gray-500">
          {timestamp && <span>{timestamp}</span>}
          {canResume && (
            <span className="text-blue-600 font-medium">View →</span>
          )}
          {!canResume && jobs.length > 1 && (
            <svg
              className={`w-4 h-4 transition-transform ${expanded ? "rotate-180" : ""}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          )}
        </div>
      </button>

      {expanded && jobs.length > 1 && (
        <ul className="border-t border-gray-200 divide-y divide-gray-100">
          {jobs.slice(1).map((job) => {
            const b = statusBadge(job.status);
            const errs = job.result_summary?.errors ?? job.errors.length ?? 0;
            const ts = formatRelativeTime(
              job.completed_at ?? job.started_at ?? job.created_at
            );
            const resume =
              onResumeJob && (job.status === "queued" || job.status === "running");
            return (
              <li
                key={job.id}
                className={`flex items-center justify-between gap-3 px-4 py-2 text-sm ${
                  resume ? "hover:bg-gray-50 cursor-pointer" : ""
                }`}
                onClick={() => {
                  if (resume) onResumeJob!(job);
                }}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span
                    className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${b.color}`}
                  >
                    {b.label}
                  </span>
                  <span className="text-gray-900 truncate">
                    <span className="font-medium">{moduleLabel(job)}</span>
                    <span className="text-gray-500"> · {jobDetail(job)}</span>
                    {errs > 0 && (
                      <span className="text-red-600"> · {errs} error{errs !== 1 ? "s" : ""}</span>
                    )}
                  </span>
                </div>
                <span className="text-xs text-gray-400 shrink-0">{ts}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
