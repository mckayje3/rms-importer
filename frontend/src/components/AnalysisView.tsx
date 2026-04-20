"use client";

import { ImportMode } from "@/types";
import type { AnalyzeResponse, RMSSession, ProcoreStats } from "@/types";

interface AnalysisViewProps {
  rmsSession: RMSSession;
  procoreStats: ProcoreStats;
  analysis: AnalyzeResponse;
  onModeSelect: (mode: ImportMode) => void;
}

const MODE_INFO: Record<ImportMode, { title: string; description: string }> = {
  [ImportMode.FULL_MIGRATION]: {
    title: "Full Migration",
    description:
      "Create all RMS submittals in Procore. Best when Procore project is empty or you want to start fresh.",
  },
  [ImportMode.SYNC_FROM_RMS]: {
    title: "Sync from RMS",
    description:
      "Update matching submittals and create new ones from RMS. RMS is the source of truth.",
  },
  [ImportMode.RECONCILE]: {
    title: "Reconcile",
    description:
      "Review and resolve differences manually. Best when both systems have unique data.",
  },
};

export function AnalysisView({
  rmsSession,
  procoreStats,
  analysis,
  onModeSelect,
}: AnalysisViewProps) {
  const { summary } = analysis;

  return (
    <div className="space-y-6">
      {/* Comparison Stats */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-blue-50 rounded-lg p-4">
          <h3 className="text-sm font-medium text-blue-800 mb-3">RMS Data</h3>
          <div className="space-y-2">
            <div className="flex justify-between">
              <span className="text-sm text-blue-700">Submittals</span>
              <span className="font-medium text-blue-900">{summary.total_rms}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-blue-700">Spec Sections</span>
              <span className="font-medium text-blue-900">
                {rmsSession.spec_section_count}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-blue-700">Revisions</span>
              <span className="font-medium text-blue-900">
                {rmsSession.revision_count}
              </span>
            </div>
          </div>
        </div>

        <div className="bg-purple-50 rounded-lg p-4">
          <h3 className="text-sm font-medium text-purple-800 mb-3">Procore Data</h3>
          <div className="space-y-2">
            <div className="flex justify-between">
              <span className="text-sm text-purple-700">Submittals</span>
              <span className="font-medium text-purple-900">{summary.total_procore}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-purple-700">Spec Sections</span>
              <span className="font-medium text-purple-900">{procoreStats.spec_section_count}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-purple-700">Revisions</span>
              <span className="font-medium text-purple-900">{procoreStats.revision_count}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Match Summary */}
      <div className="bg-gray-50 rounded-lg p-4">
        <h3 className="text-sm font-medium text-gray-800 mb-3">Match Analysis</h3>
        <div className="grid grid-cols-4 gap-4 text-center">
          <div>
            <p className="text-2xl font-bold text-green-600">{summary.matched_count}</p>
            <p className="text-xs text-gray-500">Matched</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-blue-600">{summary.rms_only_count}</p>
            <p className="text-xs text-gray-500">RMS Only</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-purple-600">{summary.procore_only_count}</p>
            <p className="text-xs text-gray-500">Procore Only</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-orange-600">{summary.conflict_count}</p>
            <p className="text-xs text-gray-500">Conflicts</p>
          </div>
        </div>
        <div className="mt-4 pt-4 border-t border-gray-200">
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-600">Match Rate</span>
            <span className="font-medium text-gray-900">
              {(summary.match_rate * 100).toFixed(1)}%
            </span>
          </div>
          <div className="mt-2 w-full bg-gray-200 rounded-full h-2">
            <div
              className="bg-green-500 h-2 rounded-full"
              style={{ width: `${summary.match_rate * 100}%` }}
            />
          </div>
        </div>
      </div>

      {/* Recommendation */}
      <div className="bg-orange-50 border border-orange-200 rounded-lg p-4">
        <div className="flex items-start gap-3">
          <div className="w-8 h-8 bg-orange-500 rounded-full flex items-center justify-center flex-shrink-0">
            <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
          </div>
          <div>
            <h3 className="text-sm font-medium text-orange-800">Recommended Mode</h3>
            <p className="text-sm text-orange-700 mt-1">{summary.recommendation_reason}</p>
          </div>
        </div>
      </div>

      {/* Mode Selection */}
      <div className="space-y-3">
        <h3 className="text-sm font-medium text-gray-700">Select Import Mode</h3>
        {Object.entries(MODE_INFO).map(([mode, info]) => {
          const isRecommended = mode === summary.recommended_mode;
          return (
            <button
              key={mode}
              onClick={() => onModeSelect(mode as ImportMode)}
              className={`
                w-full text-left p-4 rounded-lg border-2 transition-colors
                ${
                  isRecommended
                    ? "border-orange-500 bg-orange-50"
                    : "border-gray-200 hover:border-gray-300"
                }
              `}
            >
              <div className="flex items-start justify-between">
                <div>
                  <h4 className="font-medium text-gray-900">
                    {info.title}
                    {isRecommended && (
                      <span className="ml-2 text-xs bg-orange-500 text-white px-2 py-0.5 rounded">
                        Recommended
                      </span>
                    )}
                  </h4>
                  <p className="text-sm text-gray-600 mt-1">{info.description}</p>
                </div>
                <svg
                  className="w-5 h-5 text-gray-400"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9 5l7 7-7 7"
                  />
                </svg>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
