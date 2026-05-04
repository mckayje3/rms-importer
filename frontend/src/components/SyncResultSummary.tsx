"use client";

import { useState } from "react";
import type { SyncPlan } from "@/types";

/**
 * Post-import detail panel shown on the Complete step.
 *
 * Mirrors the per-section breakdown from SyncView (Creates, QA, Dates,
 * Other, Files, Flags) but with green checkmarks instead of checkboxes —
 * the user has already committed, this is a record of what was applied.
 *
 * Only renders the sections that the user actually asked to apply
 * (per `appliedOptions`). Items always render expanded by default; the
 * collapse toggle is still there for users with very long plans.
 */

interface AppliedOptions {
  creates: boolean;
  updates: boolean;
  dates: boolean;
}

interface SyncResultSummaryProps {
  plan: SyncPlan;
  appliedOptions: AppliedOptions;
  errorCount?: number;
}

const FIELD_LABELS: Record<string, string> = {
  qa_code: "QA Code",
  qc_code: "QC Code",
  info: "Info",
  title: "Title",
  type: "Type",
  paragraph: "Paragraph",
  government_received: "Government Received",
  government_returned: "Government Returned",
};

function CheckIcon() {
  return (
    <svg
      className="w-4 h-4 text-green-600 flex-shrink-0"
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2.5}
        d="M5 13l4 4L19 7"
      />
    </svg>
  );
}

function Caret({ open }: { open: boolean }) {
  return (
    <svg
      className={`w-5 h-5 text-gray-500 transition-transform ${open ? "rotate-180" : ""}`}
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
    </svg>
  );
}

export function SyncResultSummary({
  plan,
  appliedOptions,
  errorCount = 0,
}: SyncResultSummaryProps) {
  const [openSection, setOpenSection] = useState<string | null>("creates");

  // Group updates by change type, same logic as SyncView
  const qaCodeUpdates = plan.updates.filter((u) =>
    u.changes.some((c) => c.field === "qa_code")
  );
  const dateUpdates = plan.updates.filter((u) =>
    u.changes.some((c) =>
      ["government_received", "government_returned"].includes(c.field)
    )
  );
  const otherUpdates = plan.updates.filter(
    (u) => !qaCodeUpdates.includes(u) && !dateUpdates.includes(u)
  );

  const showCreates = appliedOptions.creates && plan.creates.length > 0;
  const showQa = appliedOptions.updates && qaCodeUpdates.length > 0;
  const showDates = appliedOptions.dates && dateUpdates.length > 0;
  const showOther = appliedOptions.updates && otherUpdates.length > 0;
  const showFlags = plan.flags.length > 0;
  const filesPlanned = plan.file_uploads.length;
  const showFiles = filesPlanned > 0;

  const anything = showCreates || showQa || showDates || showOther || showFiles || showFlags;
  if (!anything) return null;

  const toggle = (key: string) =>
    setOpenSection((current) => (current === key ? null : key));

  return (
    <div className="text-left max-w-2xl mx-auto mb-6 space-y-3">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-base font-semibold text-gray-900">Changes Applied</h3>
        {errorCount > 0 && (
          <span className="text-xs text-red-600">
            {errorCount} error{errorCount !== 1 ? "s" : ""} — see below
          </span>
        )}
      </div>

      {/* New Submittals */}
      {showCreates && (
        <div className="border rounded-lg overflow-hidden">
          <button
            onClick={() => toggle("creates")}
            className="w-full flex items-center justify-between p-3 bg-green-50 hover:bg-green-100 transition-colors"
          >
            <div className="flex items-center gap-3">
              <CheckIcon />
              <span className="font-medium text-green-800">
                {plan.creates.length} New Submittal{plan.creates.length !== 1 ? "s" : ""}
              </span>
            </div>
            <Caret open={openSection === "creates"} />
          </button>
          {openSection === "creates" && (
            <div className="p-4 border-t border-green-200 max-h-64 overflow-y-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-500">
                    <th className="pb-2">Section</th>
                    <th className="pb-2">Item</th>
                    <th className="pb-2">Rev</th>
                    <th className="pb-2">Title</th>
                  </tr>
                </thead>
                <tbody>
                  {plan.creates.map((c) => (
                    <tr key={c.key} className="border-t border-gray-100">
                      <td className="py-2 font-mono">{c.section}</td>
                      <td className="py-2">{c.item_no}</td>
                      <td className="py-2">{c.revision}</td>
                      <td className="py-2 truncate max-w-xs">{c.title}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* QA Code Updates */}
      {showQa && (
        <div className="border rounded-lg overflow-hidden">
          <button
            onClick={() => toggle("qa")}
            className="w-full flex items-center justify-between p-3 bg-yellow-50 hover:bg-yellow-100 transition-colors"
          >
            <div className="flex items-center gap-3">
              <CheckIcon />
              <span className="font-medium text-yellow-800">
                {qaCodeUpdates.length} QA Code Update{qaCodeUpdates.length !== 1 ? "s" : ""}
              </span>
            </div>
            <Caret open={openSection === "qa"} />
          </button>
          {openSection === "qa" && (
            <div className="p-4 border-t border-yellow-200 max-h-64 overflow-y-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-500">
                    <th className="pb-2">Submittal</th>
                    <th className="pb-2">Old</th>
                    <th className="pb-2"></th>
                    <th className="pb-2">New</th>
                  </tr>
                </thead>
                <tbody>
                  {qaCodeUpdates.map((u) => {
                    const qaChange = u.changes.find((c) => c.field === "qa_code");
                    return (
                      <tr key={u.key} className="border-t border-gray-100">
                        <td className="py-2 font-mono">{u.key.replace(/\|/g, "-")}</td>
                        <td className="py-2">
                          <span className="px-2 py-1 bg-gray-200 rounded text-gray-700">
                            {qaChange?.old_value || "-"}
                          </span>
                        </td>
                        <td className="py-2 text-gray-400">→</td>
                        <td className="py-2">
                          <span className="px-2 py-1 bg-green-200 rounded text-green-800">
                            {qaChange?.new_value || "-"}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Date Updates */}
      {showDates && (
        <div className="border rounded-lg overflow-hidden">
          <button
            onClick={() => toggle("dates")}
            className="w-full flex items-center justify-between p-3 bg-blue-50 hover:bg-blue-100 transition-colors"
          >
            <div className="flex items-center gap-3">
              <CheckIcon />
              <span className="font-medium text-blue-800">
                {dateUpdates.length} Date Update{dateUpdates.length !== 1 ? "s" : ""}
              </span>
            </div>
            <Caret open={openSection === "dates"} />
          </button>
          {openSection === "dates" && (
            <div className="p-4 border-t border-blue-200 max-h-64 overflow-y-auto">
              {dateUpdates.map((u) => (
                <div key={u.key} className="mb-3 pb-3 border-b border-gray-100 last:border-0">
                  <p className="font-mono text-sm text-gray-700 mb-1">
                    {u.key.replace(/\|/g, "-")}
                  </p>
                  <div className="pl-4 text-sm">
                    {u.changes
                      .filter((c) =>
                        ["government_received", "government_returned"].includes(c.field)
                      )
                      .map((c) => (
                        <div key={c.field} className="text-gray-600">
                          {FIELD_LABELS[c.field] || c.field}: {c.old_value || "-"} → {c.new_value || "-"}
                        </div>
                      ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Other Updates */}
      {showOther && (
        <div className="border rounded-lg overflow-hidden">
          <button
            onClick={() => toggle("other")}
            className="w-full flex items-center justify-between p-3 bg-gray-50 hover:bg-gray-100 transition-colors"
          >
            <div className="flex items-center gap-3">
              <CheckIcon />
              <span className="font-medium text-gray-800">
                {otherUpdates.length} Other Update{otherUpdates.length !== 1 ? "s" : ""}
              </span>
            </div>
            <Caret open={openSection === "other"} />
          </button>
          {openSection === "other" && (
            <div className="p-4 border-t border-gray-200 max-h-64 overflow-y-auto">
              {otherUpdates.map((u) => (
                <div key={u.key} className="mb-3 pb-3 border-b border-gray-100 last:border-0">
                  <p className="font-mono text-sm text-gray-700 mb-1">
                    {u.key.replace(/\|/g, "-")}
                  </p>
                  <div className="pl-4 text-sm">
                    {u.changes.map((c) => (
                      <div key={c.field} className="text-gray-600">
                        {FIELD_LABELS[c.field] || c.field}: {c.old_value || "-"} → {c.new_value || "-"}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Files */}
      {showFiles && (
        <div className="border border-purple-200 rounded-lg overflow-hidden">
          <button
            onClick={() => toggle("files")}
            className="w-full flex items-center justify-between p-3 bg-purple-50 hover:bg-purple-100 transition-colors"
          >
            <div className="flex items-center gap-3">
              <CheckIcon />
              <span className="font-medium text-purple-800">
                {filesPlanned} File{filesPlanned !== 1 ? "s" : ""} Uploaded &amp; Attached
              </span>
            </div>
            <Caret open={openSection === "files"} />
          </button>
          {openSection === "files" && (
            <div className="p-4 border-t border-purple-200 max-h-64 overflow-y-auto">
              <ul className="text-sm text-gray-700 space-y-1">
                {plan.file_uploads.map((f) => (
                  <li key={f.filename} className="font-mono truncate">
                    {f.filename}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Flagged */}
      {showFlags && (
        <div className="border border-orange-200 rounded-lg overflow-hidden">
          <button
            onClick={() => toggle("flags")}
            className="w-full flex items-center justify-between p-3 bg-orange-50 hover:bg-orange-100 transition-colors"
          >
            <span className="font-medium text-orange-800">
              {plan.flags.length} Item{plan.flags.length !== 1 ? "s" : ""} Flagged for Review
            </span>
            <Caret open={openSection === "flags"} />
          </button>
          {openSection === "flags" && (
            <div className="p-4 border-t border-orange-200 max-h-64 overflow-y-auto">
              <p className="text-sm text-orange-700 mb-2">
                These items exist in Procore but were not in the latest RMS export.
                They are flagged for manual review — not deleted from Procore.
              </p>
              <ul className="space-y-1 text-sm font-mono">
                {plan.flags.map((f) => (
                  <li key={f.key} className="text-gray-700">
                    {f.key.replace(/\|/g, "-")}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
