"use client";

import { useState } from "react";
import type { RFISyncPlan } from "@/types";

/**
 * Post-import detail panel shown on the Complete step after an RFI sync.
 *
 * Mirrors RFIReview's tables (Creates, Response Updates) with green
 * checkmarks instead of checkboxes. Filters by what actually happened
 * — sections only render if the corresponding result count is > 0.
 */

interface RFIImportResult {
  created: number;
  replies: number;
  responsesAdded: number;
  errors: string[];
}

interface RFIResultSummaryProps {
  plan: RFISyncPlan;
  result: RFIImportResult;
  /** Total RFI files attempted (response + non-response). */
  filesAttempted?: number;
}

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

export function RFIResultSummary({
  plan,
  result,
  filesAttempted = 0,
}: RFIResultSummaryProps) {
  const [openSection, setOpenSection] = useState<string | null>("creates");

  const showCreates = result.created > 0 && plan.creates.length > 0;
  const showResponses = result.responsesAdded > 0 && plan.response_updates.length > 0;
  const showFiles = filesAttempted > 0;
  const errorCount = result.errors.length;

  const anything = showCreates || showResponses || showFiles;
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

      {/* New RFIs created */}
      {showCreates && (
        <div className="border rounded-lg overflow-hidden">
          <button
            onClick={() => toggle("creates")}
            className="w-full flex items-center justify-between p-3 bg-green-50 hover:bg-green-100 transition-colors"
          >
            <div className="flex items-center gap-3">
              <CheckIcon />
              <span className="font-medium text-green-800">
                {result.created} New RFI{result.created !== 1 ? "s" : ""} Created
                {result.replies > 0 && (
                  <span className="text-sm font-normal text-green-700">
                    {" "}({result.replies} repl{result.replies !== 1 ? "ies" : "y"} attached)
                  </span>
                )}
              </span>
            </div>
            <Caret open={openSection === "creates"} />
          </button>
          {openSection === "creates" && (
            <div className="p-4 border-t border-green-200 max-h-64 overflow-y-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-500">
                    <th className="pb-2">RFI #</th>
                    <th className="pb-2">Subject</th>
                    <th className="pb-2 text-center">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {plan.creates.map((c) => (
                    <tr key={c.rfi_number} className="border-t border-gray-100">
                      <td className="py-2 font-mono text-xs">{c.rfi_number}</td>
                      <td className="py-2 text-gray-700">{c.subject}</td>
                      <td className="py-2 text-center">
                        <span
                          className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                            c.is_answered
                              ? "bg-green-100 text-green-700"
                              : "bg-yellow-100 text-yellow-700"
                          }`}
                        >
                          {c.is_answered ? "Answered" : "Open"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Responses added to existing RFIs */}
      {showResponses && (
        <div className="border rounded-lg overflow-hidden">
          <button
            onClick={() => toggle("responses")}
            className="w-full flex items-center justify-between p-3 bg-blue-50 hover:bg-blue-100 transition-colors"
          >
            <div className="flex items-center gap-3">
              <CheckIcon />
              <span className="font-medium text-blue-800">
                {result.responsesAdded} Response{result.responsesAdded !== 1 ? "s" : ""} Added to Existing RFIs
              </span>
            </div>
            <Caret open={openSection === "responses"} />
          </button>
          {openSection === "responses" && (
            <div className="p-4 border-t border-blue-200 max-h-64 overflow-y-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-500">
                    <th className="pb-2">RFI #</th>
                    <th className="pb-2">Response Preview</th>
                  </tr>
                </thead>
                <tbody>
                  {plan.response_updates.map((r) => (
                    <tr key={r.rfi_number} className="border-t border-gray-100">
                      <td className="py-2 font-mono text-xs">{r.rfi_number}</td>
                      <td className="py-2 text-gray-700 truncate max-w-xs">
                        {r.response_body.length > 120
                          ? r.response_body.slice(0, 120) + "…"
                          : r.response_body}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Files attached */}
      {showFiles && (
        <div className="border border-purple-200 rounded-lg overflow-hidden">
          <div className="flex items-center justify-between p-3 bg-purple-50">
            <div className="flex items-center gap-3">
              <CheckIcon />
              <span className="font-medium text-purple-800">
                {filesAttempted} RFI File{filesAttempted !== 1 ? "s" : ""} Uploaded
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
