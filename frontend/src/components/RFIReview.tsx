"use client";

import { useState, useEffect, useRef } from "react";
import { rfi as rfiApi } from "@/lib/api";
import type { RFISyncPlan, RFIJobStatus } from "@/types";

interface RFIReviewProps {
  plan: RFISyncPlan;
  summary: string;
  projectId: number;
  sessionId: string;
  companyId: number;
  rfiFiles?: File[];
  onComplete: (result: { created: number; replies: number; responsesAdded: number; errors: string[] }) => void;
  onCancel: () => void;
}

export function RFIReview({
  plan,
  summary,
  projectId,
  sessionId,
  companyId,
  rfiFiles = [],
  onComplete,
  onCancel,
}: RFIReviewProps) {
  const [applyCreates, setApplyCreates] = useState(true);
  const [applyReplies, setApplyReplies] = useState(true);
  const [applyResponseUpdates, setApplyResponseUpdates] = useState(true);
  const [executing, setExecuting] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<RFIJobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Stable ref for onComplete to avoid useEffect re-fires
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  // Poll job status
  useEffect(() => {
    if (!jobId) return;

    const poll = async () => {
      try {
        const status = await rfiApi.getJobStatus(jobId);
        setJobStatus(status);

        if (status.status === "completed" || status.status === "failed") {
          if (pollRef.current) clearInterval(pollRef.current);
          onCompleteRef.current({
            created: status.created,
            replies: status.replies_added,
            responsesAdded: status.responses_added,
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

  // Split picked files for the preview banner. The unified job handles both
  // categories — this is just so the user can see what's going where.
  const responseFiles = rfiFiles.filter(f => /^RFI-\d+\s*Response/i.test(f.name));
  const otherRfiFiles = rfiFiles.filter(
    f => /^RFI-\d+/i.test(f.name) && !/^RFI-\d+\s*Response/i.test(f.name)
  );

  const handleExecute = async () => {
    setExecuting(true);
    setError(null);

    try {
      const options = {
        creates: applyCreates,
        replies: applyReplies,
        responseUpdates: applyResponseUpdates,
        responseUpdateItems: applyResponseUpdates ? plan.response_updates : [],
      };

      // Always go through the unified endpoint when files are picked, so
      // creates, replies, and file attaches happen as one ordered job.
      const result = rfiFiles.length > 0
        ? await rfiApi.executeWithFiles(projectId, sessionId, companyId, options, rfiFiles)
        : await rfiApi.execute(projectId, sessionId, companyId, options);

      if (result.job_id) {
        setJobId(result.job_id);
      } else {
        onComplete({
          created: result.created,
          replies: result.replies_added,
          responsesAdded: 0,
          errors: result.errors,
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
      setExecuting(false);
    }
  };

  const totalOperations = plan.creates.length + (applyResponseUpdates ? plan.response_updates.length : 0);
  const hasCreates = plan.creates.length > 0;
  const hasResponseUpdates = plan.response_updates.length > 0;
  // Files alone are reason enough to enable Apply — non-response files attach
  // to existing RFIs in the unified job's Phase 3 even when nothing else is
  // happening. Without this, picking files but having no CSV-driven changes
  // would hide the Apply button entirely.
  const hasFilesToAttach = rfiFiles.length > 0;
  const hasAnythingToDo = plan.has_changes || hasFilesToAttach;
  const nothingSelected =
    !applyCreates && !applyReplies && !applyResponseUpdates && !hasFilesToAttach;

  // Show progress if running
  if (jobId && jobStatus) {
    const completedOps = jobStatus.created + jobStatus.responses_added + (jobStatus.errors?.length || 0);
    const progress = jobStatus.total > 0
      ? Math.round((completedOps / jobStatus.total) * 100)
      : 0;

    return (
      <div className="space-y-6">
        <div className="text-center py-4">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-orange-500 mx-auto mb-4"></div>
          <p className="text-gray-700 font-medium">Importing RFIs to Procore...</p>
          <p className="text-sm text-gray-500 mt-1">
            {jobStatus.created > 0 && `${jobStatus.created} created`}
            {jobStatus.replies_added > 0 && `, ${jobStatus.replies_added} replies`}
            {jobStatus.responses_added > 0 && `${jobStatus.created > 0 ? ", " : ""}${jobStatus.responses_added} responses added`}
            {jobStatus.errors.length > 0 && `, ${jobStatus.errors.length} errors`}
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
        <p className="text-sm text-gray-700">{summary}</p>
      </div>

      {/* Creates table */}
      {hasCreates && (
        <div>
          <h3 className="text-sm font-medium text-gray-700 mb-2">
            RFIs to Create ({plan.creates.length})
          </h3>
          <div className="max-h-64 overflow-y-auto border border-gray-200 rounded-lg">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="text-left px-3 py-2 text-gray-600">RFI #</th>
                  <th className="text-left px-3 py-2 text-gray-600">Subject</th>
                  <th className="text-center px-3 py-2 text-gray-600">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {plan.creates.map((c) => (
                  <tr key={c.rfi_number} className="hover:bg-gray-50">
                    <td className="px-3 py-2 font-mono text-xs">{c.rfi_number}</td>
                    <td className="px-3 py-2 text-gray-700">{c.subject}</td>
                    <td className="px-3 py-2 text-center">
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                        c.is_answered
                          ? "bg-green-100 text-green-700"
                          : "bg-yellow-100 text-yellow-700"
                      }`}>
                        {c.is_answered ? "Answered" : "Open"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Response updates table */}
      {hasResponseUpdates && (
        <div>
          <h3 className="text-sm font-medium text-gray-700 mb-2">
            Responses to Add ({plan.response_updates.length})
          </h3>
          <p className="text-xs text-gray-500 mb-2">
            These RFIs exist in Procore but are missing the government response from RMS.
          </p>
          <div className="max-h-48 overflow-y-auto border border-gray-200 rounded-lg">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="text-left px-3 py-2 text-gray-600">RFI #</th>
                  <th className="text-left px-3 py-2 text-gray-600">Response Preview</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {plan.response_updates.map((r) => (
                  <tr key={r.rfi_number} className="hover:bg-gray-50">
                    <td className="px-3 py-2 font-mono text-xs">{r.rfi_number}</td>
                    <td className="px-3 py-2 text-gray-700 truncate max-w-xs">
                      {r.response_body.length > 120
                        ? r.response_body.slice(0, 120) + "..."
                        : r.response_body}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!hasCreates && !hasResponseUpdates && plan.already_exist > 0 && (
        <p className="text-sm text-gray-500">
          {plan.already_exist} RFI{plan.already_exist !== 1 ? "s" : ""} already exist in Procore with responses up to date.
        </p>
      )}

      {plan.already_exist > 0 && (hasCreates || hasResponseUpdates) && (
        <p className="text-sm text-gray-500">
          {plan.already_exist - plan.response_updates.length > 0 &&
            `${plan.already_exist - plan.response_updates.length} RFI${plan.already_exist - plan.response_updates.length !== 1 ? "s" : ""} already up to date in Procore.`}
        </p>
      )}

      {/* No CSV-driven changes — but files may still need to attach */}
      {!plan.has_changes && !hasFilesToAttach && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-center">
          <p className="text-sm text-blue-700 font-medium">All RFIs are already in Procore with responses up to date.</p>
          <p className="text-xs text-blue-600 mt-1">Nothing to import.</p>
        </div>
      )}
      {!plan.has_changes && hasFilesToAttach && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <p className="text-sm text-blue-700 font-medium">All RFIs are already in Procore with responses up to date.</p>
          <p className="text-xs text-blue-600 mt-1">No CSV-driven changes — but the {rfiFiles.length} file{rfiFiles.length !== 1 ? "s" : ""} you selected will still upload and attach to the matching RFI{rfiFiles.length !== 1 ? "s" : ""} when you click Apply.</p>
        </div>
      )}

      {/* Options */}
      {plan.has_changes && (
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-gray-700">Options</h3>
          {hasCreates && (
            <>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={applyCreates}
                  onChange={(e) => setApplyCreates(e.target.checked)}
                  className="rounded border-gray-300 text-orange-500 focus:ring-orange-500"
                />
                <span className="text-sm text-gray-700">
                  Create {plan.creates.length} new RFI{plan.creates.length !== 1 ? "s" : ""}
                </span>
              </label>
              <label className="flex items-center gap-2 ml-6">
                <input
                  type="checkbox"
                  checked={applyReplies}
                  onChange={(e) => setApplyReplies(e.target.checked)}
                  disabled={!applyCreates}
                  className="rounded border-gray-300 text-orange-500 focus:ring-orange-500"
                />
                <span className={`text-sm ${applyCreates ? "text-gray-700" : "text-gray-400"}`}>
                  Add government responses to new RFIs
                </span>
              </label>
            </>
          )}
          {hasResponseUpdates && (
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={applyResponseUpdates}
                onChange={(e) => setApplyResponseUpdates(e.target.checked)}
                className="rounded border-gray-300 text-orange-500 focus:ring-orange-500"
              />
              <span className="text-sm text-gray-700">
                Add {plan.response_updates.length} response{plan.response_updates.length !== 1 ? "s" : ""} to existing RFIs
              </span>
            </label>
          )}
        </div>
      )}

      {/* File plan summary */}
      {rfiFiles.length > 0 && (
        <div className="bg-purple-50 border border-purple-200 rounded-lg p-3 space-y-1">
          {responseFiles.length > 0 && (applyReplies || applyResponseUpdates) && (
            <p className="text-sm text-purple-700">
              {responseFiles.length} response file{responseFiles.length !== 1 ? "s" : ""} will
              be attached to replies.
            </p>
          )}
          {otherRfiFiles.length > 0 && (
            <p className="text-sm text-purple-700">
              {otherRfiFiles.length} other RFI file{otherRfiFiles.length !== 1 ? "s" : ""} will
              be attached to {hasCreates ? "new and existing" : "their"} RFIs.
            </p>
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
        {hasAnythingToDo && (
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
