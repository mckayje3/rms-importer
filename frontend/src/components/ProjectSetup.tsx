"use client";

import { useState, useEffect } from "react";
import { setup } from "@/lib/api";
import type { ProjectDiscovery, ProjectConfigData } from "@/types";

interface ProjectSetupProps {
  projectId: number;
  companyId: number;
  onSetupComplete: (config: ProjectConfigData) => void;
  onAutoSkip?: (config: ProjectConfigData) => void;
}

type SetupStep = "loading" | "welcome" | "prerequisites" | "custom-fields" | "status-mapping" | "review";

export function ProjectSetup({ projectId, companyId, onSetupComplete, onAutoSkip }: ProjectSetupProps) {
  const [setupStep, setSetupStep] = useState<SetupStep>("loading");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [discovery, setDiscovery] = useState<ProjectDiscovery | null>(null);

  // Config state
  const [statusMode, setStatusMode] = useState<"qa_code" | "rms_status">("qa_code");
  const [statusMap, setStatusMap] = useState<Record<string, string>>({});
  const [sdTypeMap, setSdTypeMap] = useState<Record<string, string>>({});

  // Normalize status map values: backend may send {name, id} dicts or plain strings
  const normalizeStatusMap = (map: Record<string, unknown>): Record<string, string> => {
    const result: Record<string, string> = {};
    for (const [key, val] of Object.entries(map)) {
      if (typeof val === "string") {
        result[key] = val;
      } else if (val && typeof val === "object" && "name" in val) {
        result[key] = (val as { name: string }).name;
      }
    }
    return result;
  };
  const [paragraphField, setParagraphField] = useState<string>("");
  const [infoField, setInfoField] = useState<string>("");

  useEffect(() => {
    async function loadConfig() {
      setError(null);
      try {
        // Check if config already exists
        try {
          const existing = await setup.getConfig(projectId);
          const config = existing.config_data;

          // Auto-skip: project is already configured
          if (config.setup_completed && onAutoSkip) {
            onAutoSkip(config);
            return;
          }

          // Config exists but not completed — load it for editing
          setStatusMode(config.status_mode || "qa_code");
          setStatusMap(normalizeStatusMap(config.status_map || {}));
          setSdTypeMap(config.sd_type_map || {});
          setParagraphField(config.custom_fields?.paragraph || "");
          setInfoField(config.custom_fields?.info || "");

          const disc = await setup.discover(projectId, companyId);
          setDiscovery(disc);
          setSetupStep("custom-fields");
        } catch {
          // No config — first time setup
          const disc = await setup.discover(projectId, companyId);
          setDiscovery(disc);
          const suggested = disc.suggested_config;
          setStatusMode(suggested.status_mode || "qa_code");
          setStatusMap(normalizeStatusMap(suggested.status_map));
          setSdTypeMap(suggested.sd_type_map);
          setParagraphField(suggested.custom_fields?.paragraph || "");
          setInfoField(suggested.custom_fields?.info || "");
          setSetupStep("welcome");
        }
      } catch (err) {
        setError("Failed to load project configuration");
        console.error(err);
        setSetupStep("welcome");
      }
    }
    loadConfig();
  }, [projectId, companyId, onAutoSkip]);

  const handleSaveAndContinue = async () => {
    setSaving(true);
    setError(null);
    try {
      const configData: ProjectConfigData = {
        status_mode: statusMode,
        status_map: statusMap,
        sd_type_map: sdTypeMap,
        custom_fields: {
          ...(paragraphField ? { paragraph: paragraphField } : {}),
          ...(infoField ? { info: infoField } : {}),
        },
        setup_completed: true,
      };
      await setup.saveConfig(projectId, companyId, configData);
      onSetupComplete(configData);
    } catch (err) {
      setError("Failed to save configuration");
      console.error(err);
    } finally {
      setSaving(false);
    }
  };

  const customFields = discovery?.custom_fields || [];
  const rawStatuses = discovery?.statuses || [{ name: "Draft" }, { name: "Open" }, { name: "Closed" }];
  // Normalize: backend may return strings or {name, id} objects
  const availableStatuses = rawStatuses.map((s: string | { name: string }) =>
    typeof s === "string" ? s : s.name
  );
  const hasCustomFields = customFields.length > 0;
  const hasParagraphSuggestion = customFields.some(cf => cf.label.toLowerCase().includes("paragraph"));
  const hasInfoSuggestion = customFields.some(cf => cf.label.toLowerCase().includes("info"));

  // --- Loading ---
  if (setupStep === "loading") {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500 mx-auto mb-4"></div>
          <p className="text-gray-600">Checking project configuration...</p>
        </div>
      </div>
    );
  }

  // --- Step 1: Welcome ---
  if (setupStep === "welcome") {
    return (
      <div className="space-y-6">
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-5">
          <h3 className="text-base font-semibold text-blue-900 mb-2">First-Time Setup</h3>
          <p className="text-sm text-blue-800">
            This is the first time using RMS Importer with this project. We&apos;ll walk you
            through a quick setup to make sure your Procore project is ready to receive RMS data.
          </p>
        </div>

        <div className="space-y-4">
          <h3 className="text-sm font-semibold text-gray-900">What this setup does:</h3>
          <div className="space-y-3">
            <div className="flex gap-3">
              <div className="flex-shrink-0 w-6 h-6 rounded-full bg-orange-100 text-orange-600 flex items-center justify-center text-xs font-bold">1</div>
              <div>
                <p className="text-sm font-medium text-gray-900">Check Procore prerequisites</p>
                <p className="text-xs text-gray-500">Verify custom fields exist on your submittal form</p>
              </div>
            </div>
            <div className="flex gap-3">
              <div className="flex-shrink-0 w-6 h-6 rounded-full bg-orange-100 text-orange-600 flex items-center justify-center text-xs font-bold">2</div>
              <div>
                <p className="text-sm font-medium text-gray-900">Map custom fields</p>
                <p className="text-xs text-gray-500">Connect RMS fields (Paragraph, Info) to your Procore custom fields</p>
              </div>
            </div>
            <div className="flex gap-3">
              <div className="flex-shrink-0 w-6 h-6 rounded-full bg-orange-100 text-orange-600 flex items-center justify-center text-xs font-bold">3</div>
              <div>
                <p className="text-sm font-medium text-gray-900">Configure status mapping</p>
                <p className="text-xs text-gray-500">Choose how RMS data maps to Procore submittal statuses</p>
              </div>
            </div>
          </div>
        </div>

        <p className="text-xs text-gray-400">
          This only needs to be done once per project. Future syncs will skip this step.
        </p>

        <button
          onClick={() => setSetupStep("prerequisites")}
          className="w-full py-3 px-4 rounded-lg font-medium bg-orange-500 text-white hover:bg-orange-600 transition-colors"
        >
          Get Started
        </button>
      </div>
    );
  }

  // --- Step 2: Prerequisites ---
  if (setupStep === "prerequisites") {
    return (
      <div className="space-y-6">
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}

        <div>
          <h3 className="text-sm font-semibold text-gray-900 mb-1">Procore Prerequisites</h3>
          <p className="text-xs text-gray-500 mb-4">
            The RMS Importer uses custom fields on your Procore submittal form to store
            RMS-specific data. These must be created in the Procore admin UI before importing.
          </p>
        </div>

        {/* Custom Fields Check */}
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          <div className="bg-gray-50 px-4 py-3 border-b border-gray-200">
            <h4 className="text-sm font-medium text-gray-900">Custom Fields on Submittals</h4>
          </div>
          <div className="p-4 space-y-3">
            {hasCustomFields ? (
              <>
                <div className="flex items-start gap-2">
                  <svg className="w-5 h-5 text-green-500 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                  <div>
                    <p className="text-sm text-green-800 font-medium">
                      {customFields.length} custom field{customFields.length !== 1 ? "s" : ""} found
                    </p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {customFields.map(cf => cf.label).join(", ")}
                    </p>
                  </div>
                </div>
                {hasParagraphSuggestion && hasInfoSuggestion ? (
                  <p className="text-xs text-green-700 bg-green-50 rounded p-2">
                    Paragraph and Info fields detected. They&apos;ll be auto-mapped in the next step.
                  </p>
                ) : (
                  <p className="text-xs text-yellow-700 bg-yellow-50 rounded p-2">
                    We&apos;ll ask you to map the right fields in the next step. Look for fields that
                    store the spec paragraph reference and the Info classification (GA/FIO/S).
                  </p>
                )}
              </>
            ) : (
              <>
                <div className="flex items-start gap-2">
                  <svg className="w-5 h-5 text-yellow-500 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
                  </svg>
                  <div>
                    <p className="text-sm text-yellow-800 font-medium">No custom fields found</p>
                    <p className="text-xs text-gray-600 mt-1">
                      To store RMS Paragraph and Info data, create custom fields in Procore:
                    </p>
                  </div>
                </div>
                <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 text-xs text-yellow-900 space-y-2">
                  <p className="font-medium">How to create custom fields:</p>
                  <ol className="list-decimal list-inside space-y-1 text-yellow-800">
                    <li>In Procore, go to <span className="font-medium">Company Admin</span></li>
                    <li>Navigate to <span className="font-medium">Tool Settings &gt; Submittals</span></li>
                    <li>Under <span className="font-medium">Configurable Fieldsets</span>, click Edit</li>
                    <li>Add a text field named <span className="font-medium">&quot;Paragraph&quot;</span></li>
                    <li>Add a text field named <span className="font-medium">&quot;Info&quot;</span></li>
                    <li>Save the fieldset</li>
                  </ol>
                  <p className="text-yellow-700 mt-2">
                    You can also skip this and import without custom fields. Paragraph and Info data
                    won&apos;t be transferred to Procore.
                  </p>
                </div>
              </>
            )}
          </div>
        </div>

        {/* Statuses Check */}
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          <div className="bg-gray-50 px-4 py-3 border-b border-gray-200">
            <h4 className="text-sm font-medium text-gray-900">Submittal Statuses</h4>
          </div>
          <div className="p-4">
            <div className="flex items-start gap-2">
              <svg className="w-5 h-5 text-green-500 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
              <div>
                <p className="text-sm text-green-800 font-medium">
                  {availableStatuses.length} status{availableStatuses.length !== 1 ? "es" : ""} available
                </p>
                <p className="text-xs text-gray-500 mt-0.5">
                  {availableStatuses.join(", ")}
                </p>
              </div>
            </div>
            <p className="text-xs text-gray-500 mt-2">
              Procore includes Draft, Open, and Closed by default. Custom statuses can be
              added in Company Admin &gt; Tool Settings &gt; Submittals.
            </p>
          </div>
        </div>

        {/* Submittal Types note */}
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          <div className="bg-gray-50 px-4 py-3 border-b border-gray-200">
            <h4 className="text-sm font-medium text-gray-900">Submittal Types (SD Numbers)</h4>
          </div>
          <div className="p-4">
            <div className="flex items-start gap-2">
              <svg className="w-5 h-5 text-green-500 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
              <div>
                <p className="text-sm text-green-800 font-medium">No setup required</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  SD types (SD-01 through SD-11) are set as text when creating submittals.
                  The UFGS standard names are pre-configured.
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className="flex gap-4">
          <button
            onClick={() => setSetupStep("welcome")}
            className="py-3 px-4 rounded-lg font-medium border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors"
          >
            Back
          </button>
          <button
            onClick={() => setSetupStep("custom-fields")}
            className="flex-1 py-3 px-4 rounded-lg font-medium bg-orange-500 text-white hover:bg-orange-600 transition-colors"
          >
            {hasCustomFields ? "Continue to Field Mapping" : "Continue Without Custom Fields"}
          </button>
        </div>
      </div>
    );
  }

  // --- Step 3: Custom Field Mapping ---
  if (setupStep === "custom-fields") {
    return (
      <div className="space-y-6">
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}

        <div>
          <h3 className="text-sm font-semibold text-gray-900 mb-1">Map Custom Fields</h3>
          <p className="text-xs text-gray-500 mb-4">
            Select which Procore custom fields correspond to each RMS field.
            {!hasCustomFields && " No custom fields were found — you can skip this step."}
          </p>
        </div>

        <div className="space-y-4">
          {/* Paragraph field */}
          <div className="border border-gray-200 rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-medium text-gray-900">Paragraph</label>
              {paragraphField && (
                <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">Mapped</span>
              )}
            </div>
            <p className="text-xs text-gray-500 mb-2">
              Stores the specification paragraph reference for each submittal.
            </p>
            <select
              value={paragraphField}
              onChange={(e) => setParagraphField(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
              disabled={!hasCustomFields}
            >
              <option value="">{hasCustomFields ? "— Not mapped —" : "— No custom fields available —"}</option>
              {customFields.map((cf) => (
                <option key={cf.field_key} value={cf.field_key}>
                  {cf.label} ({cf.data_type})
                </option>
              ))}
            </select>
          </div>

          {/* Info field */}
          <div className="border border-gray-200 rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-medium text-gray-900">Info</label>
              {infoField && (
                <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">Mapped</span>
              )}
            </div>
            <p className="text-xs text-gray-500 mb-2">
              Stores the Info classification: GA (Government Approval), FIO (For Information Only), or S (Standard).
            </p>
            <select
              value={infoField}
              onChange={(e) => setInfoField(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
              disabled={!hasCustomFields}
            >
              <option value="">{hasCustomFields ? "— Not mapped —" : "— No custom fields available —"}</option>
              {customFields.map((cf) => (
                <option key={cf.field_key} value={cf.field_key}>
                  {cf.label} ({cf.data_type})
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex gap-4">
          <button
            onClick={() => setSetupStep("prerequisites")}
            className="py-3 px-4 rounded-lg font-medium border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors"
          >
            Back
          </button>
          <button
            onClick={() => setSetupStep("status-mapping")}
            className="flex-1 py-3 px-4 rounded-lg font-medium bg-orange-500 text-white hover:bg-orange-600 transition-colors"
          >
            Continue
          </button>
        </div>
      </div>
    );
  }

  // --- Step 4: Status Mapping ---
  if (setupStep === "status-mapping") {
    const QA_CODES = [
      { key: "a", label: "A — Approved", description: "Approved as submitted" },
      { key: "b", label: "B — Approved as Noted", description: "Approved except as noted" },
      { key: "c", label: "C — Resubmit Required", description: "Approved, resubmission required" },
      { key: "d", label: "D — Returned", description: "Returned by separate correspondence" },
      { key: "e", label: "E — Disapproved", description: "Disapproved (see attached)" },
      { key: "f", label: "F — Receipt Acknowledged", description: "For information only" },
      { key: "g", label: "G — Other", description: "Other (specify)" },
      { key: "x", label: "X — Receipt Acknowledged", description: "Does not comply with requirements" },
    ];

    const RMS_STATUSES = [
      { key: "outstanding", label: "Outstanding", description: "Submittal not yet submitted or action needed" },
      { key: "complete", label: "Complete", description: "Submittal process finished" },
      { key: "in review", label: "In Review", description: "Submittal currently being reviewed" },
    ];

    const DEFAULT_QA_MAP: Record<string, string> = { a: "closed", b: "closed", c: "open", d: "open", e: "open", f: "closed", g: "open", x: "closed" };
    const DEFAULT_RMS_MAP: Record<string, string> = { outstanding: "Draft", complete: "Closed", "in review": "Open" };

    const mappingItems = statusMode === "qa_code" ? QA_CODES : RMS_STATUSES;

    const handleModeChange = (mode: "qa_code" | "rms_status") => {
      setStatusMode(mode);
      setStatusMap(mode === "qa_code" ? DEFAULT_QA_MAP : DEFAULT_RMS_MAP);
    };

    return (
      <div className="space-y-6">
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}

        <div>
          <h3 className="text-sm font-semibold text-gray-900 mb-1">Status Mapping</h3>
          <p className="text-xs text-gray-500 mb-4">
            Choose how Procore submittal statuses are determined from RMS data.
          </p>
        </div>

        {/* Mode selector */}
        <div className="space-y-3">
          <label className="text-sm font-medium text-gray-700">Derive status from:</label>
          <div className="grid grid-cols-2 gap-3">
            <button
              onClick={() => handleModeChange("qa_code")}
              className={`border rounded-lg p-4 text-left transition-colors ${
                statusMode === "qa_code"
                  ? "border-orange-500 bg-orange-50"
                  : "border-gray-200 hover:border-gray-300"
              }`}
            >
              <p className="text-sm font-medium text-gray-900">QA Code</p>
              <p className="text-xs text-gray-500 mt-1">
                Use the government QA review code (A-G, X) to set status. Submittals without a QA code keep their current status.
              </p>
            </button>
            <button
              onClick={() => handleModeChange("rms_status")}
              className={`border rounded-lg p-4 text-left transition-colors ${
                statusMode === "rms_status"
                  ? "border-orange-500 bg-orange-50"
                  : "border-gray-200 hover:border-gray-300"
              }`}
            >
              <p className="text-sm font-medium text-gray-900">RMS Status</p>
              <p className="text-xs text-gray-500 mt-1">
                Use the RMS status field (Outstanding, Complete, In Review) to set status.
              </p>
            </button>
          </div>
        </div>

        {/* Mapping table */}
        <div className="space-y-3">
          {mappingItems.map(({ key, label, description }) => (
            <div key={key} className="border border-gray-200 rounded-lg p-4">
              <div className="flex items-center gap-3">
                <div className="flex-1">
                  <p className="text-sm font-medium text-gray-900">{label}</p>
                  <p className="text-xs text-gray-500">{description}</p>
                </div>
                <span className="text-gray-400 text-lg">&rarr;</span>
                <select
                  value={statusMap[key] || ""}
                  onChange={(e) => setStatusMap((prev) => ({ ...prev, [key]: e.target.value }))}
                  className="w-32 border border-gray-300 rounded-lg px-3 py-2 text-sm"
                >
                  {availableStatuses.map((status) => (
                    <option key={status} value={status}>
                      {status}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          ))}
        </div>

        <div className="flex gap-4">
          <button
            onClick={() => setSetupStep("custom-fields")}
            className="py-3 px-4 rounded-lg font-medium border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors"
          >
            Back
          </button>
          <button
            onClick={() => setSetupStep("review")}
            className="flex-1 py-3 px-4 rounded-lg font-medium bg-orange-500 text-white hover:bg-orange-600 transition-colors"
          >
            Review & Save
          </button>
        </div>
      </div>
    );
  }

  // --- Step 5: Review & Save ---
  if (setupStep === "review") {
    return (
      <div className="space-y-6">
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}

        <div>
          <h3 className="text-sm font-semibold text-gray-900 mb-1">Review Configuration</h3>
          <p className="text-xs text-gray-500 mb-4">
            Confirm your settings. You can reconfigure these later from the Setup step.
          </p>
        </div>

        {/* Custom Fields Summary */}
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          <div className="bg-gray-50 px-4 py-2 border-b border-gray-200 flex items-center justify-between">
            <h4 className="text-sm font-medium text-gray-900">Custom Fields</h4>
            <button onClick={() => setSetupStep("custom-fields")} className="text-xs text-orange-600 hover:text-orange-700">Edit</button>
          </div>
          <div className="p-4 space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-gray-600">Paragraph</span>
              <span className={paragraphField ? "font-medium text-gray-900" : "text-gray-400 italic"}>
                {paragraphField
                  ? customFields.find(cf => cf.field_key === paragraphField)?.label || paragraphField
                  : "Not mapped"}
              </span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-600">Info</span>
              <span className={infoField ? "font-medium text-gray-900" : "text-gray-400 italic"}>
                {infoField
                  ? customFields.find(cf => cf.field_key === infoField)?.label || infoField
                  : "Not mapped"}
              </span>
            </div>
          </div>
        </div>

        {/* Status Mapping Summary */}
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          <div className="bg-gray-50 px-4 py-2 border-b border-gray-200 flex items-center justify-between">
            <h4 className="text-sm font-medium text-gray-900">
              Status Mapping
              <span className="ml-2 text-xs font-normal text-gray-500">
                ({statusMode === "qa_code" ? "from QA Code" : "from RMS Status"})
              </span>
            </h4>
            <button onClick={() => setSetupStep("status-mapping")} className="text-xs text-orange-600 hover:text-orange-700">Edit</button>
          </div>
          <div className="p-4 space-y-2">
            {Object.entries(statusMap).map(([source, procore]) => (
              <div key={source} className="flex justify-between text-sm">
                <span className="text-gray-600 uppercase">{source}</span>
                <span className="font-medium text-gray-900">{procore}</span>
              </div>
            ))}
          </div>
        </div>

        {/* SD Types Summary */}
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          <div className="bg-gray-50 px-4 py-2 border-b border-gray-200">
            <h4 className="text-sm font-medium text-gray-900">Submittal Types</h4>
          </div>
          <div className="p-4">
            <p className="text-xs text-gray-500">
              {Object.keys(sdTypeMap).length} SD types configured (UFGS standard)
            </p>
          </div>
        </div>

        <div className="flex gap-4">
          <button
            onClick={() => setSetupStep("status-mapping")}
            className="py-3 px-4 rounded-lg font-medium border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors"
          >
            Back
          </button>
          <button
            onClick={handleSaveAndContinue}
            disabled={saving}
            className={`
              flex-1 py-3 px-4 rounded-lg font-medium transition-colors flex items-center justify-center gap-2
              ${saving
                ? "bg-gray-200 text-gray-500 cursor-not-allowed"
                : "bg-orange-500 text-white hover:bg-orange-600"
              }
            `}
          >
            {saving ? (
              <>
                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
                Saving...
              </>
            ) : (
              "Save & Continue"
            )}
          </button>
        </div>
      </div>
    );
  }

  return null;
}
