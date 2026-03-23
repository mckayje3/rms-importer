"use client";

import { useState, useEffect } from "react";
import {
  Header,
  StepIndicator,
  ProjectSelector,
  RMSUpload,
  AnalysisView,
  SyncView,
} from "@/components";
import { auth, submittals, sync, health } from "@/lib/api";
import type {
  AppStep,
  ProcoreCompany,
  ProcoreProject,
  ProcoreStats,
  RMSSession,
  AnalyzeResponse,
  ImportMode,
  SyncAnalysisResponse,
  SyncExecuteResponse,
} from "@/types";

export default function Home() {
  const [step, setStep] = useState<AppStep>("auth");
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [company, setCompany] = useState<ProcoreCompany | null>(null);
  const [project, setProject] = useState<ProcoreProject | null>(null);
  const [procoreStats, setProcoreStats] = useState<ProcoreStats | null>(null);
  const [rmsSession, setRmsSession] = useState<RMSSession | null>(null);
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);
  const [selectedMode, setSelectedMode] = useState<ImportMode | null>(null);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<{
    imported: number;
    updated: number;
    errors: string[];
  } | null>(null);
  const [syncAnalysis, setSyncAnalysis] = useState<SyncAnalysisResponse | null>(null);
  const [syncResult, setSyncResult] = useState<SyncExecuteResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Check authentication on mount
  useEffect(() => {
    async function checkHealth() {
      try {
        await health();
        // If we get here, backend is running
        // Check URL for OAuth callback
        const params = new URLSearchParams(window.location.search);
        if (params.get("auth") === "success") {
          const sessionId = params.get("session_id");
          if (sessionId) {
            sessionStorage.setItem("auth_session", sessionId);
          }
          setIsAuthenticated(true);
          setStep("select-project");
          // Clean up URL
          window.history.replaceState({}, "", "/");
        }
      } catch {
        setError("Cannot connect to backend server");
      }
    }
    checkHealth();
  }, []);

  const handleLogin = async () => {
    try {
      const response = await fetch(auth.getLoginUrl());
      const data = await response.json();
      window.location.href = data.auth_url;
    } catch {
      setError("Failed to start login flow");
    }
  };

  const handleLogout = async () => {
    try {
      await auth.logout();
      setIsAuthenticated(false);
      setStep("auth");
      setCompany(null);
      setProject(null);
      setRmsSession(null);
      setAnalysis(null);
    } catch {
      // Ignore logout errors
    }
  };

  const handleProjectSelect = (
    selectedCompany: ProcoreCompany,
    selectedProject: ProcoreProject,
    stats: ProcoreStats
  ) => {
    setCompany(selectedCompany);
    setProject(selectedProject);
    setProcoreStats(stats);
    setStep("upload-rms");
  };

  const handleRmsUpload = async (session: RMSSession) => {
    setRmsSession(session);

    if (!project || !company) return;

    try {
      // Check if a baseline exists for this project
      const baseline = await sync.getBaseline(project.id);

      if (baseline.has_baseline) {
        // Incremental sync: analyze against baseline
        setStep("analyze");
        const syncResult = await sync.analyze(
          project.id,
          session.session_id,
          company.id
        );
        setSyncAnalysis(syncResult);
        setStep("sync-review");
      } else {
        // No baseline: use original full migration flow
        setStep("analyze");
        const result = await submittals.analyze(project.id, session.session_id);
        setAnalysis(result);
      }
    } catch (err) {
      setError("Failed to analyze data");
      console.error(err);
    }
  };

  const handleModeSelect = (mode: ImportMode) => {
    setSelectedMode(mode);
    setStep("review");
  };

  const handleSyncExecute = async (options: {
    creates: boolean;
    updates: boolean;
    files: boolean;
  }) => {
    if (!project || !company || !rmsSession) return;

    setImporting(true);
    setError(null);

    try {
      const result = await sync.execute(
        project.id,
        rmsSession.session_id,
        company.id,
        options
      );
      setSyncResult(result);
      setStep("complete");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sync failed");
    } finally {
      setImporting(false);
    }
  };

  const handleImport = async () => {
    if (!project || !rmsSession || !selectedMode) return;

    setImporting(true);
    setError(null);

    try {
      const result = await submittals.import(
        project.id,
        rmsSession.session_id,
        selectedMode
      );
      setImportResult(result);
      setStep("complete");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setImporting(false);
    }
  };

  const renderStepContent = () => {
    switch (step) {
      case "auth":
        return (
          <div className="text-center py-12">
            <div className="w-20 h-20 bg-orange-500 rounded-2xl flex items-center justify-center mx-auto mb-6">
              <span className="text-white font-bold text-3xl">R</span>
            </div>
            <h2 className="text-2xl font-bold text-gray-900 mb-2">
              Connect to Procore
            </h2>
            <p className="text-gray-600 mb-8 max-w-md mx-auto">
              Sign in with your Procore account to start importing submittal data from RMS.
            </p>
            <button
              onClick={handleLogin}
              className="bg-orange-500 text-white px-8 py-3 rounded-lg font-medium hover:bg-orange-600 transition-colors"
            >
              Connect with Procore
            </button>
          </div>
        );

      case "select-project":
        return (
          <div>
            <h2 className="text-xl font-bold text-gray-900 mb-2">
              Select Project
            </h2>
            <p className="text-gray-600 mb-6">
              Choose the Procore project where you want to import RMS data.
            </p>
            <ProjectSelector onProjectSelect={handleProjectSelect} />
          </div>
        );

      case "upload-rms":
        return (
          <div>
            <h2 className="text-xl font-bold text-gray-900 mb-2">
              Upload RMS Files
            </h2>
            <p className="text-gray-600 mb-6">
              Upload the three RMS export files to begin the import process.
            </p>
            <RMSUpload onUploadComplete={handleRmsUpload} />
          </div>
        );

      case "analyze":
        if (!analysis || !rmsSession || !procoreStats) {
          return (
            <div className="flex items-center justify-center py-12">
              <div className="text-center">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500 mx-auto mb-4"></div>
                <p className="text-gray-600">Analyzing data...</p>
              </div>
            </div>
          );
        }
        return (
          <div>
            <h2 className="text-xl font-bold text-gray-900 mb-2">
              Analysis Results
            </h2>
            <p className="text-gray-600 mb-6">
              Review the comparison between RMS and Procore data, then select an import mode.
            </p>
            <AnalysisView
              rmsSession={rmsSession}
              procoreStats={procoreStats}
              analysis={analysis}
              onModeSelect={handleModeSelect}
            />
          </div>
        );

      case "sync-review":
        if (!syncAnalysis) {
          return (
            <div className="flex items-center justify-center py-12">
              <div className="text-center">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500 mx-auto mb-4"></div>
                <p className="text-gray-600">Analyzing changes...</p>
              </div>
            </div>
          );
        }
        return (
          <div>
            <h2 className="text-xl font-bold text-gray-900 mb-2">
              Sync Review
            </h2>
            <p className="text-gray-600 mb-6">
              Review changes detected between your RMS data and the stored baseline.
            </p>
            <SyncView
              baseline={syncAnalysis.baseline}
              plan={syncAnalysis.plan}
              onExecute={handleSyncExecute}
              onCancel={() => setStep("upload-rms")}
              isExecuting={importing}
            />
          </div>
        );

      case "review":
        return (
          <div>
            <h2 className="text-xl font-bold text-gray-900 mb-2">
              Confirm Import
            </h2>
            <p className="text-gray-600 mb-6">
              Review your selections and start the import.
            </p>

            <div className="bg-gray-50 rounded-lg p-6 mb-6 space-y-4">
              <div className="flex justify-between">
                <span className="text-gray-600">Project</span>
                <span className="font-medium">{project?.name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Import Mode</span>
                <span className="font-medium capitalize">
                  {selectedMode?.replace(/_/g, " ")}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">RMS Submittals</span>
                <span className="font-medium">{analysis?.summary.total_rms}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">To Create</span>
                <span className="font-medium text-green-600">
                  {analysis?.summary.rms_only_count}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">To Update</span>
                <span className="font-medium text-blue-600">
                  {analysis?.summary.matched_count}
                </span>
              </div>
            </div>

            <div className="flex gap-4">
              <button
                onClick={() => setStep("analyze")}
                className="flex-1 py-3 px-4 rounded-lg font-medium border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors"
              >
                Back
              </button>
              <button
                onClick={handleImport}
                disabled={importing}
                className="flex-1 py-3 px-4 rounded-lg font-medium bg-orange-500 text-white hover:bg-orange-600 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {importing ? (
                  <>
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
                    Importing...
                  </>
                ) : (
                  "Start Import"
                )}
              </button>
            </div>
          </div>
        );

      case "complete":
        return (
          <div className="text-center py-12">
            <div className="w-20 h-20 bg-green-500 rounded-full flex items-center justify-center mx-auto mb-6">
              <svg
                className="w-10 h-10 text-white"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M5 13l4 4L19 7"
                />
              </svg>
            </div>
            <h2 className="text-2xl font-bold text-gray-900 mb-2">
              Import Complete!
            </h2>
            <p className="text-gray-600 mb-6">
              Your RMS data has been imported to Procore.
            </p>

            {syncResult && (
              <div className="bg-gray-50 rounded-lg p-6 max-w-sm mx-auto mb-6">
                <div className="space-y-3">
                  <div className="flex justify-between">
                    <span className="text-gray-600">Status</span>
                    <span className={`font-medium ${syncResult.status === "completed" ? "text-green-600" : "text-yellow-600"}`}>
                      {syncResult.status === "completed" ? "Completed" : "Partial"}
                    </span>
                  </div>
                  {syncResult.created > 0 && (
                    <div className="flex justify-between">
                      <span className="text-gray-600">Created</span>
                      <span className="font-medium text-green-600">{syncResult.created}</span>
                    </div>
                  )}
                  {syncResult.updated > 0 && (
                    <div className="flex justify-between">
                      <span className="text-gray-600">Updated</span>
                      <span className="font-medium text-blue-600">{syncResult.updated}</span>
                    </div>
                  )}
                  {syncResult.files_uploaded > 0 && (
                    <div className="flex justify-between">
                      <span className="text-gray-600">Files Uploaded</span>
                      <span className="font-medium text-purple-600">{syncResult.files_uploaded}</span>
                    </div>
                  )}
                  {syncResult.flagged > 0 && (
                    <div className="flex justify-between">
                      <span className="text-gray-600">Flagged for Review</span>
                      <span className="font-medium text-orange-600">{syncResult.flagged}</span>
                    </div>
                  )}
                  {syncResult.errors.length > 0 && (
                    <div className="mt-3 pt-3 border-t border-gray-200">
                      <p className="text-sm font-medium text-red-600 mb-1">
                        {syncResult.errors.length} error(s)
                      </p>
                      <ul className="text-xs text-red-500 space-y-1">
                        {syncResult.errors.slice(0, 5).map((e, i) => (
                          <li key={i}>{e}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {syncResult.baseline_updated && (
                    <p className="text-xs text-gray-500 mt-2">Baseline updated for next sync.</p>
                  )}
                </div>
              </div>
            )}

            {importResult && !syncResult && (
              <div className="bg-gray-50 rounded-lg p-6 max-w-sm mx-auto mb-6">
                <div className="space-y-3">
                  <div className="flex justify-between">
                    <span className="text-gray-600">Created</span>
                    <span className="font-medium text-green-600">
                      {importResult.imported}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">Updated</span>
                    <span className="font-medium text-blue-600">
                      {importResult.updated}
                    </span>
                  </div>
                  {importResult.errors.length > 0 && (
                    <div className="flex justify-between">
                      <span className="text-gray-600">Errors</span>
                      <span className="font-medium text-red-600">
                        {importResult.errors.length}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            )}

            <button
              onClick={() => {
                setStep("select-project");
                setRmsSession(null);
                setAnalysis(null);
                setSelectedMode(null);
                setImportResult(null);
                setSyncAnalysis(null);
                setSyncResult(null);
              }}
              className="bg-orange-500 text-white px-8 py-3 rounded-lg font-medium hover:bg-orange-600 transition-colors"
            >
              Import Another Project
            </button>
          </div>
        );

      default:
        return null;
    }
  };

  return (
    <div className="min-h-screen">
      <Header isAuthenticated={isAuthenticated} onLogout={handleLogout} />

      {isAuthenticated && step !== "auth" && step !== "complete" && (
        <div className="bg-white border-b border-gray-200">
          <div className="max-w-4xl mx-auto">
            <StepIndicator currentStep={step} />
          </div>
        </div>
      )}

      <main className="max-w-2xl mx-auto px-6 py-8">
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
            <p className="text-sm text-red-700">{error}</p>
            <button
              onClick={() => setError(null)}
              className="text-sm text-red-600 underline mt-2"
            >
              Dismiss
            </button>
          </div>
        )}

        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          {renderStepContent()}
        </div>
      </main>
    </div>
  );
}
