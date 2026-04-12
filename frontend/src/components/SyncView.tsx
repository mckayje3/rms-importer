"use client";

import { useState } from "react";
import { FolderFileUpload } from "./FolderFileUpload";
import { FileJobProgress } from "./FileJobProgress";

interface FieldChange {
  field: string;
  old_value: string | null;
  new_value: string | null;
}

interface CreateAction {
  key: string;
  section: string;
  item_no: number;
  revision: number;
  title: string;
  type: string | null;
}

interface UpdateAction {
  key: string;
  procore_id: number;
  changes: FieldChange[];
}

interface FlagAction {
  key: string;
  procore_id: number;
  reason: string;
}

interface FileUploadAction {
  filename: string;
  submittal_keys: string[];
}

interface SyncPlan {
  mode: "full_migration" | "incremental";
  creates: CreateAction[];
  updates: UpdateAction[];
  flags: FlagAction[];
  file_uploads: FileUploadAction[];
  files_already_uploaded: number;
  has_changes: boolean;
  summary: string;
}

interface BaselineInfo {
  has_baseline: boolean;
  last_sync: string | null;
  submittal_count: number;
  file_count: number;
}

interface SyncViewProps {
  baseline: BaselineInfo;
  plan: SyncPlan;
  onExecute: (options: { creates: boolean; updates: boolean; dates: boolean }) => void;
  onBootstrap?: () => Promise<void>;
  onCancel: () => void;
  onDone?: () => void;
  isExecuting: boolean;
  projectId?: number;
  rmsSessionId?: string;
  companyId?: number;
  fileJobId?: string | null;
  onFileJobIdChange?: (jobId: string | null) => void;
}

// Field display names
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

export function SyncView({
  baseline,
  plan,
  onExecute,
  onBootstrap,
  onCancel,
  onDone,
  isExecuting,
  projectId,
  rmsSessionId,
  companyId,
  fileJobId: externalFileJobId,
  onFileJobIdChange,
}: SyncViewProps) {
  const [expandedSection, setExpandedSection] = useState<string | null>(null);
  const [applyCreates, setApplyCreates] = useState(true);
  const [applyUpdates, setApplyUpdates] = useState(true);
  const [applyDates, setApplyDates] = useState(true);
  const [bootstrapping, setBootstrapping] = useState(false);
  const [internalFileJobId, setInternalFileJobId] = useState<string | null>(null);
  // Prefer external (parent-managed) state when provided so the file job
  // survives navigation away from this screen.
  const fileJobId = externalFileJobId !== undefined ? externalFileJobId : internalFileJobId;
  const setFileJobId = (id: string | null) => {
    setInternalFileJobId(id);
    onFileJobIdChange?.(id);
  };

  const toggleSection = (section: string) => {
    setExpandedSection(expandedSection === section ? null : section);
  };

  const handleExecute = () => {
    onExecute({
      creates: applyCreates,
      updates: applyUpdates,
      dates: applyDates,
    });
  };

  // Group updates by change type for better display
  const qaCodeUpdates = plan.updates.filter((u) =>
    u.changes.some((c) => c.field === "qa_code")
  );
  const dateUpdates = plan.updates.filter((u) =>
    u.changes.some((c) =>
      ["government_received", "government_returned"].includes(c.field)
    )
  );
  const otherUpdates = plan.updates.filter(
    (u) =>
      !qaCodeUpdates.includes(u) && !dateUpdates.includes(u)
  );

  return (
    <div className="space-y-6">
      {/* Baseline Info */}
      <div className="bg-gray-50 rounded-lg p-4">
        <h3 className="text-sm font-medium text-gray-800 mb-3">Baseline Status</h3>
        {baseline.has_baseline ? (
          <div className="space-y-2">
            <div className="flex justify-between">
              <span className="text-sm text-gray-600">Last Synced</span>
              <span className="font-medium text-gray-900">
                {baseline.last_sync
                  ? new Date(baseline.last_sync).toLocaleString()
                  : "Unknown"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-gray-600">Submittals in Baseline</span>
              <span className="font-medium text-gray-900">{baseline.submittal_count}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-gray-600">Files Uploaded</span>
              <span className="font-medium text-gray-900">{baseline.file_count}</span>
            </div>
          </div>
        ) : (
          <p className="text-sm text-gray-600">
            No baseline found. This will be a full migration.
          </p>
        )}
      </div>

      {/* Bootstrap warning for full migration when project already has data */}
      {plan.mode === "full_migration" && onBootstrap && (
        <div className="bg-amber-50 border border-amber-300 rounded-lg p-4">
          <h3 className="text-sm font-bold text-amber-800 mb-2">
            Existing Project Detected
          </h3>
          <p className="text-sm text-amber-700 mb-3">
            No baseline exists, so the sync wants to create {plan.creates.length} submittals.
            If this project was already migrated (e.g. via PowerShell scripts), you should
            <strong> bootstrap the baseline</strong> first. This matches your RMS data against
            existing Procore submittals without creating or modifying anything.
          </p>
          <button
            onClick={async () => {
              setBootstrapping(true);
              try {
                await onBootstrap();
              } finally {
                setBootstrapping(false);
              }
            }}
            disabled={bootstrapping}
            className="bg-amber-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-amber-700 disabled:opacity-50"
          >
            {bootstrapping ? "Bootstrapping..." : "Bootstrap Baseline"}
          </button>
        </div>
      )}

      {/* Sync Plan Summary */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <h3 className="text-sm font-medium text-blue-800 mb-2">Changes Detected</h3>
        <p className="text-blue-700">{plan.summary}</p>
      </div>

      {!plan.has_changes && (
        <div className="text-center py-8">
          <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h3 className="text-lg font-medium text-gray-900">Everything is in sync!</h3>
          <p className="text-gray-600 mt-1">No changes detected between RMS and baseline.</p>
        </div>
      )}

      {plan.has_changes && (
        <>
          {/* New Submittals */}
          {plan.creates.length > 0 && (
            <div className="border rounded-lg overflow-hidden">
              <button
                onClick={() => toggleSection("creates")}
                className="w-full flex items-center justify-between p-4 bg-green-50 hover:bg-green-100 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={applyCreates}
                    onChange={(e) => {
                      e.stopPropagation();
                      setApplyCreates(e.target.checked);
                    }}
                    className="w-4 h-4 text-green-600"
                  />
                  <span className="font-medium text-green-800">
                    {plan.creates.length} New Submittals
                  </span>
                </div>
                <svg
                  className={`w-5 h-5 text-green-600 transition-transform ${
                    expandedSection === "creates" ? "rotate-180" : ""
                  }`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>
              {expandedSection === "creates" && (
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
          {qaCodeUpdates.length > 0 && (
            <div className="border rounded-lg overflow-hidden">
              <button
                onClick={() => toggleSection("qa")}
                className="w-full flex items-center justify-between p-4 bg-yellow-50 hover:bg-yellow-100 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={applyUpdates}
                    onChange={(e) => {
                      e.stopPropagation();
                      setApplyUpdates(e.target.checked);
                    }}
                    className="w-4 h-4 text-yellow-600"
                  />
                  <span className="font-medium text-yellow-800">
                    {qaCodeUpdates.length} QA Code Updates
                  </span>
                </div>
                <svg
                  className={`w-5 h-5 text-yellow-600 transition-transform ${
                    expandedSection === "qa" ? "rotate-180" : ""
                  }`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>
              {expandedSection === "qa" && (
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
          {dateUpdates.length > 0 && (
            <div className="border rounded-lg overflow-hidden">
              <button
                onClick={() => toggleSection("dates")}
                className="w-full flex items-center justify-between p-4 bg-blue-50 hover:bg-blue-100 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={applyDates}
                    onChange={(e) => {
                      e.stopPropagation();
                      setApplyDates(e.target.checked);
                    }}
                    className="w-4 h-4 text-blue-600"
                  />
                  <span className="font-medium text-blue-800">
                    {dateUpdates.length} Date Updates
                  </span>
                </div>
                <svg
                  className={`w-5 h-5 text-blue-600 transition-transform ${
                    expandedSection === "dates" ? "rotate-180" : ""
                  }`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>
              {expandedSection === "dates" && (
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
          {otherUpdates.length > 0 && (
            <div className="border rounded-lg overflow-hidden">
              <button
                onClick={() => toggleSection("other")}
                className="w-full flex items-center justify-between p-4 bg-gray-50 hover:bg-gray-100 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={applyUpdates}
                    onChange={(e) => {
                      e.stopPropagation();
                      setApplyUpdates(e.target.checked);
                    }}
                    className="w-4 h-4 text-gray-600"
                  />
                  <span className="font-medium text-gray-800">
                    {otherUpdates.length} Other Updates
                  </span>
                </div>
                <svg
                  className={`w-5 h-5 text-gray-600 transition-transform ${
                    expandedSection === "other" ? "rotate-180" : ""
                  }`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>
              {expandedSection === "other" && (
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

          {/* Flagged Items */}
          {plan.flags.length > 0 && (
            <div className="border border-orange-200 rounded-lg overflow-hidden">
              <button
                onClick={() => toggleSection("flags")}
                className="w-full flex items-center justify-between p-4 bg-orange-50 hover:bg-orange-100 transition-colors"
              >
                <span className="font-medium text-orange-800">
                  {plan.flags.length} Items Removed (Flagged for Review)
                </span>
                <svg
                  className={`w-5 h-5 text-orange-600 transition-transform ${
                    expandedSection === "flags" ? "rotate-180" : ""
                  }`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>
              {expandedSection === "flags" && (
                <div className="p-4 border-t border-orange-200 max-h-64 overflow-y-auto">
                  <p className="text-sm text-orange-700 mb-3">
                    These items exist in Procore but were not in the latest RMS export.
                    They will be flagged for manual review - not automatically deleted.
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

          {/* Actions */}
          <div className="flex gap-4 pt-4 border-t">
            <button
              onClick={onCancel}
              disabled={isExecuting}
              className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={handleExecute}
              disabled={isExecuting || (!applyCreates && !applyUpdates)}
              className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {isExecuting ? (
                <>
                  <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    />
                  </svg>
                  Syncing...
                </>
              ) : (
                "Apply Selected Changes"
              )}
            </button>
          </div>
        </>
      )}

      {/* File Uploads — always visible */}
      <div className="border rounded-lg overflow-hidden">
        <button
          onClick={() => toggleSection("files")}
          className="w-full flex items-center justify-between p-4 bg-purple-50 hover:bg-purple-100 transition-colors"
        >
          <span className="font-medium text-purple-800">
            File Uploads
            {plan.files_already_uploaded > 0 && (
              <span className="ml-2 text-sm font-normal text-gray-500">
                ({plan.files_already_uploaded} already uploaded)
              </span>
            )}
          </span>
          <svg
            className={`w-5 h-5 text-purple-600 transition-transform ${
              expandedSection === "files" ? "rotate-180" : ""
            }`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
        {expandedSection === "files" && (
          <div className="p-4 border-t border-purple-200 space-y-3">
            {fileJobId ? (
              <FileJobProgress
                projectId={projectId!}
                jobId={fileJobId}
                label="files"
                onComplete={() => {}}
              />
            ) : projectId && rmsSessionId && companyId ? (
              <FolderFileUpload
                projectId={projectId}
                rmsSessionId={rmsSessionId}
                companyId={companyId}
                onUploadStarted={setFileJobId}
              />
            ) : (
              <p className="text-sm text-gray-500">
                File upload not available in this context.
              </p>
            )}
          </div>
        )}
      </div>

      {/* Done button — shown when no submittal changes to apply */}
      {!plan.has_changes && onDone && (
        <div className="pt-4 border-t">
          <button
            onClick={onDone}
            className="w-full px-4 py-3 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700 transition-colors"
          >
            Done
          </button>
        </div>
      )}
    </div>
  );
}
