"use client";

import { useState, useEffect } from "react";
import {
  Header,
  StepIndicator,
  ProjectSelector,
  RMSUpload,
  AnalysisView,
  SyncView,
  ProjectSetup,
  ToolSelector,
  RFIUpload,
  RFIReview,
  RFIFileUpload,
} from "@/components";
import { FileJobProgress } from "@/components/FileJobProgress";
import { auth, projects as projectsApi, submittals, sync, setup, health, rfi as rfiApi, debugRfiReply } from "@/lib/api";
import { useEmbeddedContext } from "@/lib/useEmbeddedContext";
import type {
  AppStep,
  ToolType,
  ProcoreCompany,
  ProcoreProject,
  ProcoreStats,
  RMSSession,
  AnalyzeResponse,
  ImportMode,
  SyncAnalysisResponse,
  SyncExecuteResponse,
  ProjectConfigData,
  FileJobStatus,
  RFISession,
  RFIAnalyzeResponse,
} from "@/types";

export default function Home() {
  const embedded = useEmbeddedContext();
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
  const [fileJobId, setFileJobId] = useState<string | null>(null);
  const [recentJobs, setRecentJobs] = useState<FileJobStatus[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [autoSelectingProject, setAutoSelectingProject] = useState(false);
  const [projectConfig, setProjectConfig] = useState<ProjectConfigData | null>(null);
  const [selectedTool, setSelectedTool] = useState<ToolType | null>(null);
  const [rfiSession, setRfiSession] = useState<RFISession | null>(null);
  const [rfiAnalysis, setRfiAnalysis] = useState<RFIAnalyzeResponse | null>(null);
  const [rfiResult, setRfiResult] = useState<{ created: number; replies: number; responsesAdded: number; errors: string[] } | null>(null);
  const [rfiFiles, setRfiFiles] = useState<File[]>([]);

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

          // If this is a popup window (opened by embedded iframe for OAuth),
          // send the session back to the opener and close
          if (window.opener) {
            if (sessionId) {
              window.opener.postMessage(
                { type: "procore-auth-success", sessionId },
                "*"
              );
            }
            window.close();
            return;
          }

          // Standard flow — set auth and continue
          if (sessionId) {
            sessionStorage.setItem("auth_session", sessionId);
          }
          setIsAuthenticated(true);
          setStep("select-project");
          window.history.replaceState({}, "", "/");
        } else {
          // Check for existing session (e.g. page refresh)
          const existingSession = sessionStorage.getItem("auth_session");
          if (existingSession) {
            setIsAuthenticated(true);
            setStep("select-project");
          }
        }
      } catch {
        setError("Cannot connect to backend server");
      }
    }
    checkHealth();
  }, []);

  // Auto-select project when embedded with Procore params
  useEffect(() => {
    if (
      !embedded.isEmbedded ||
      !embedded.projectId ||
      !embedded.companyId ||
      !isAuthenticated ||
      step !== "select-project" ||
      autoSelectingProject
    ) return;

    async function autoSelect() {
      setAutoSelectingProject(true);
      try {
        // Fetch companies to find the matching one
        const companies = await projectsApi.getCompanies();
        const matchedCompany = companies.find(c => c.id === embedded.companyId);
        if (!matchedCompany) {
          setError(`Company ${embedded.companyId} not found in your Procore account`);
          setAutoSelectingProject(false);
          return;
        }

        // Fetch projects to find the matching one
        const projectList = await projectsApi.getProjects(matchedCompany.id);
        const matchedProject = projectList.find(p => p.id === embedded.projectId);
        if (!matchedProject) {
          setError(`Project ${embedded.projectId} not found in company ${matchedCompany.name}`);
          setAutoSelectingProject(false);
          return;
        }

        // Check for active sync job before anything else
        try {
          const jobResult = await sync.listJobs(matchedProject.id, 1);
          const activeJob = jobResult.jobs.find(
            (j) => j.status === "queued" || j.status === "running"
          );
          if (activeJob) {
            // Skip stats + setup — go straight to progress
            setCompany(matchedCompany);
            setProject(matchedProject);
            setSyncResult({
              status: "background",
              created: 0,
              updated: 0,
              files_uploaded: 0,
              flagged: 0,
              errors: [],
              baseline_updated: false,
              update_job_id: activeJob.id,
            });
            setStep("complete");
            return;
          }
        } catch {
          // Ignore — fall through to normal flow
        }

        // Fetch stats
        const stats = await projectsApi.getStats(matchedProject.id, matchedCompany.id);

        // Set state and advance to upload step
        setCompany(matchedCompany);
        setProject(matchedProject);
        setProcoreStats(stats);
        setStep("project-setup");
      } catch (err) {
        setError("Failed to auto-select project from Procore context");
        console.error(err);
      } finally {
        setAutoSelectingProject(false);
      }
    }
    autoSelect();
  }, [embedded, isAuthenticated, step, autoSelectingProject]);

  // Check for in-progress sync jobs when entering a project
  useEffect(() => {
    if (!project || !isAuthenticated) return;
    if (step !== "upload-rms" && step !== "project-setup" && step !== "select-tool") return;

    async function checkActiveJobs() {
      try {
        const result = await sync.listJobs(project!.id, 1);
        const activeJob = result.jobs.find(
          (j) => j.status === "queued" || j.status === "running"
        );
        if (activeJob) {
          setSyncResult({
            status: "background",
            created: 0,
            updated: 0,
            files_uploaded: 0,
            flagged: 0,
            errors: [],
            baseline_updated: false,
            update_job_id: activeJob.id,
          });
          setStep("complete");
        }
      } catch {
        // Ignore — not critical
      }
    }
    checkActiveJobs();
  }, [project, isAuthenticated, step]);

  // On the complete page, fetch recent jobs so the user can see file uploads
  // and other background work that may have run independently of the current
  // sync result. Also recovers a stray active file job into fileJobId if one
  // exists and isn't already being shown by syncResult.update_job_id.
  useEffect(() => {
    if (step !== "complete" || !project || !isAuthenticated) return;

    let cancelled = false;
    async function loadRecentJobs() {
      try {
        const result = await sync.listJobs(project!.id, 5);
        if (cancelled) return;
        setRecentJobs(result.jobs);

        // If there's an active job we're not already tracking, attach it to
        // fileJobId so its progress shows on this screen.
        const tracked = new Set<string>();
        if (syncResult?.update_job_id) tracked.add(syncResult.update_job_id);
        if (fileJobId) tracked.add(fileJobId);
        const orphanActive = result.jobs.find(
          (j) =>
            (j.status === "queued" || j.status === "running") &&
            !tracked.has(j.id)
        );
        if (orphanActive) {
          setFileJobId(orphanActive.id);
        }
      } catch {
        // Ignore — not critical
      }
    }
    loadRecentJobs();
    return () => {
      cancelled = true;
    };
  }, [step, project, isAuthenticated, syncResult?.update_job_id, fileJobId]);

  const handleLogin = async () => {
    try {
      const response = await fetch(auth.getLoginUrl());
      const data = await response.json();

      if (embedded.isEmbedded) {
        // Open OAuth in a popup — redirect-based OAuth won't work inside an iframe
        const width = 600;
        const height = 700;
        const left = window.screenX + (window.innerWidth - width) / 2;
        const top = window.screenY + (window.innerHeight - height) / 2;
        const popup = window.open(
          data.auth_url,
          "procore-auth",
          `width=${width},height=${height},left=${left},top=${top},popup=yes`
        );

        // Listen for the OAuth callback to land back on our frontend
        const handleMessage = (event: MessageEvent) => {
          if (event.data?.type === "procore-auth-success" && event.data?.sessionId) {
            sessionStorage.setItem("auth_session", event.data.sessionId);
            setIsAuthenticated(true);
            setStep("select-project");
            window.removeEventListener("message", handleMessage);
          }
        };
        window.addEventListener("message", handleMessage);

        // Fallback: poll for popup close (user may have completed auth)
        if (popup) {
          const pollTimer = setInterval(() => {
            if (popup.closed) {
              clearInterval(pollTimer);
              window.removeEventListener("message", handleMessage);
              // Check if auth was set by the callback page
              const session = sessionStorage.getItem("auth_session");
              if (session && !isAuthenticated) {
                setIsAuthenticated(true);
                setStep("select-project");
              }
            }
          }, 500);
        }
      } else {
        // Standard redirect flow for standalone mode
        window.location.href = data.auth_url;
      }
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
    setStep("project-setup");
  };

  const handleSetupComplete = (config: ProjectConfigData) => {
    setProjectConfig(config);
    setStep("select-tool");
  };

  const handleToolSelect = (tool: ToolType) => {
    setSelectedTool(tool);
    if (tool === "submittals") {
      setStep("upload-rms");
    } else if (tool === "rfis") {
      setStep("rfi-upload");
    }
  };

  const handleRfiUpload = async (session: RFISession, files: File[]) => {
    setRfiSession(session);
    setRfiFiles(files);
    if (!project || !company) return;

    // Show loading state while analyzing
    setRfiAnalysis(null);
    setStep("rfi-review");

    try {
      const analysis = await rfiApi.analyze(project.id, session.session_id, company.id);
      setRfiAnalysis(analysis);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to analyze RFIs");
      console.error(err);
      // Reset back to upload so user isn't stuck on spinner
      setStep("rfi-upload");
    }
  };

  const handleRmsUpload = async (session: RMSSession) => {
    setRmsSession(session);

    if (!project || !company) return;

    try {
      // Always use sync analyze - it handles both full migration and incremental
      setStep("analyze");
      const syncResult = await sync.analyze(
        project.id,
        session.session_id,
        company.id
      );
      setSyncAnalysis(syncResult);
      setStep("sync-review");
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
    dates: boolean;
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

      case "project-setup":
        if (!project || !company) return null;
        return (
          <div>
            <h2 className="text-xl font-bold text-gray-900 mb-2">
              Project Setup
            </h2>
            <p className="text-gray-600 mb-6">
              Configure how RMS data maps to this Procore project.
            </p>
            <ProjectSetup
              projectId={project.id}
              companyId={company.id}
              onSetupComplete={handleSetupComplete}
              onAutoSkip={handleSetupComplete}
            />
          </div>
        );

      case "select-tool":
        return (
          <div>
            <h2 className="text-xl font-bold text-gray-900 mb-2">
              Select Tool
            </h2>
            <p className="text-gray-600 mb-6">
              Choose which RMS data you want to import into Procore.
            </p>
            <ToolSelector onSelect={handleToolSelect} />
          </div>
        );

      case "upload-rms":
        return (
          <div>
            <h2 className="text-xl font-bold text-gray-900 mb-2">
              Upload RMS Files
            </h2>
            <p className="text-gray-600 mb-6">
              Upload your RMS export files to begin the import process.
            </p>
            <RMSUpload
              onUploadComplete={handleRmsUpload}
              onBack={() => {
                setSelectedTool(null);
                setStep("select-tool");
              }}
            />
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
              onBootstrap={async () => {
                if (!project || !company || !rmsSession) return;
                const result = await sync.bootstrap(project.id, rmsSession.session_id, company.id);
                alert(`Baseline bootstrapped: ${result.matched} matched, ${result.unmatched} unmatched out of ${result.total_rms} RMS submittals.`);
                // Re-analyze with the new baseline
                const syncResult = await sync.analyze(project.id, rmsSession.session_id, company.id);
                setSyncAnalysis(syncResult);
              }}
              onCancel={() => setStep("upload-rms")}
              onDone={() => {
                setSyncResult({
                  status: "completed",
                  created: 0,
                  updated: 0,
                  files_uploaded: 0,
                  flagged: 0,
                  errors: [],
                  baseline_updated: true,
                });
                setStep("complete");
              }}
              isExecuting={importing}
              projectId={project?.id}
              rmsSessionId={rmsSession?.session_id}
              companyId={company?.id}
              fileJobId={fileJobId}
              onFileJobIdChange={setFileJobId}
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

      case "rfi-upload":
        return (
          <div>
            <h2 className="text-xl font-bold text-gray-900 mb-2">
              Upload RFI Report
            </h2>
            <p className="text-gray-600 mb-6">
              Upload the &quot;All Requests for Information&quot; CSV report from RMS.
            </p>
            <RFIUpload
              onUploadComplete={handleRfiUpload}
              onBack={() => {
                setSelectedTool(null);
                setStep("select-tool");
              }}
            />
          </div>
        );

      case "rfi-review":
        if (!rfiAnalysis || !rfiSession) {
          return (
            <div className="flex items-center justify-center py-12">
              <div className="text-center">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500 mx-auto mb-4"></div>
                <p className="text-gray-600">Analyzing RFIs...</p>
              </div>
            </div>
          );
        }
        return (
          <div>
            <h2 className="text-xl font-bold text-gray-900 mb-2">
              RFI Import Review
            </h2>
            <p className="text-gray-600 mb-6">
              Review RFIs to be imported into Procore.
            </p>
            <RFIReview
              plan={rfiAnalysis.plan}
              summary={rfiAnalysis.summary}
              projectId={project!.id}
              sessionId={rfiSession.session_id}
              companyId={company!.id}
              rfiFiles={rfiFiles}
              onComplete={(result) => {
                setRfiResult(result);
                setStep("complete");
              }}
              onCancel={() => setStep("rfi-upload")}
            />
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
              {syncResult?.update_job_id ? "Sync In Progress" : "Import Complete!"}
            </h2>
            <p className="text-gray-600 mb-6">
              {syncResult?.update_job_id
                ? "Your sync is running in the background. You can navigate away safely."
                : rfiResult
                  ? "Your RFIs have been imported to Procore."
                  : "Your RMS data has been imported to Procore."}
            </p>

            {/* Static result panel — only shown for synchronous completions
                (no background job). When update_job_id is set, FileJobProgress
                below shows the live state instead. */}
            {syncResult && !syncResult.update_job_id && (
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

            {syncResult?.update_job_id && project && (
              <div className="max-w-md mx-auto mb-6">
                <p className="text-sm font-medium text-gray-700 mb-2 text-left">
                  Submittal sync
                </p>
                <FileJobProgress
                  projectId={project.id}
                  jobId={syncResult.update_job_id}
                  label="submittals"
                  onComplete={() => {}}
                />
              </div>
            )}

            {fileJobId && project && fileJobId !== syncResult?.update_job_id && (
              <div className="max-w-md mx-auto mb-6">
                <p className="text-sm font-medium text-gray-700 mb-2 text-left">
                  File upload
                </p>
                <FileJobProgress
                  projectId={project.id}
                  jobId={fileJobId}
                  label="files"
                  onComplete={() => {}}
                />
              </div>
            )}

            {recentJobs.length > 0 && (
              <div className="max-w-md mx-auto mb-6 text-left">
                <details className="bg-gray-50 rounded-lg p-4">
                  <summary className="text-sm font-medium text-gray-700 cursor-pointer">
                    Recent activity ({recentJobs.length})
                  </summary>
                  <ul className="mt-3 space-y-2 text-xs">
                    {recentJobs.map((job) => {
                      const summary = job.result_summary;
                      const isFileJob = summary && summary.uploaded != null && summary.created == null;
                      const label = isFileJob ? "File upload" : "Submittal sync";
                      const detail = summary
                        ? isFileJob
                          ? `${summary.uploaded} / ${summary.total} files`
                          : `${summary.created ?? 0} created, ${summary.updated ?? 0} updated${summary.files ? `, ${summary.files} files` : ""}`
                        : `${job.uploaded_files} / ${job.total_files}`;
                      const statusColor =
                        job.status === "completed" ? "text-green-600"
                        : job.status === "failed" ? "text-red-600"
                        : job.status === "running" || job.status === "queued" ? "text-blue-600"
                        : "text-gray-600";
                      return (
                        <li key={job.id} className="flex justify-between gap-2">
                          <span className="text-gray-700">
                            <span className="font-medium">{label}</span>
                            <span className="text-gray-500"> — {detail}</span>
                            {summary && summary.errors > 0 && (
                              <span className="text-red-500"> ({summary.errors} errors)</span>
                            )}
                          </span>
                          <span className={`font-medium ${statusColor}`}>{job.status}</span>
                        </li>
                      );
                    })}
                  </ul>
                </details>
              </div>
            )}

            {rfiResult && (
              <div className="bg-gray-50 rounded-lg p-6 max-w-sm mx-auto mb-6">
                <div className="space-y-3">
                  {rfiResult.created > 0 && (
                    <div className="flex justify-between">
                      <span className="text-gray-600">RFIs Created</span>
                      <span className="font-medium text-green-600">{rfiResult.created}</span>
                    </div>
                  )}
                  {rfiResult.replies > 0 && (
                    <div className="flex justify-between">
                      <span className="text-gray-600">Replies Added</span>
                      <span className="font-medium text-blue-600">{rfiResult.replies}</span>
                    </div>
                  )}
                  {rfiResult.responsesAdded > 0 && (
                    <div className="flex justify-between">
                      <span className="text-gray-600">Responses Added</span>
                      <span className="font-medium text-blue-600">{rfiResult.responsesAdded}</span>
                    </div>
                  )}
                  {rfiResult.created === 0 && rfiResult.replies === 0 && rfiResult.responsesAdded === 0 && rfiResult.errors.length === 0 && (
                    <p className="text-sm text-gray-500 text-center">No changes made.</p>
                  )}
                  {rfiResult.errors.length > 0 && (
                    <div className="mt-3 pt-3 border-t border-gray-200">
                      <p className="text-sm font-medium text-red-600 mb-1">
                        {rfiResult.errors.length} error(s)
                      </p>
                      <ul className="text-xs text-red-500 space-y-1">
                        {rfiResult.errors.slice(0, 5).map((e, i) => (
                          <li key={i}>{e}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            )}

            {selectedTool === "rfis" && project && company && (
              <div className="max-w-md mx-auto mb-6 text-left">
                <RFIFileUpload
                  projectId={project.id}
                  companyId={company.id}
                  excludeFiles={rfiFiles.filter(f => /^RFI-\d+\s*Response/i.test(f.name)).map(f => f.name)}
                />
              </div>
            )}

            {/* Temporary debug button for 403 investigation */}
            {selectedTool === "rfis" && project && company && rfiResult && rfiResult.errors.length > 0 && (
              <div className="max-w-md mx-auto mb-6">
                <button
                  onClick={async () => {
                    try {
                      // RFI-0001 Procore ID
                      const result = await debugRfiReply(project!.id, 598134326828811, company!.id);
                      alert(JSON.stringify(result, null, 2));
                    } catch (err) {
                      alert("Debug failed: " + (err instanceof Error ? err.message : String(err)));
                    }
                  }}
                  className="px-4 py-2 text-sm bg-gray-200 text-gray-700 rounded hover:bg-gray-300"
                >
                  Debug RFI Reply (RFI-0001)
                </button>
              </div>
            )}

            {importResult && !syncResult && !rfiResult && (
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
                setStep(embedded.isEmbedded ? "select-tool" : "select-project");
                setRmsSession(null);
                setAnalysis(null);
                setSelectedMode(null);
                setImportResult(null);
                setSyncAnalysis(null);
                setSyncResult(null);
                setProjectConfig(null);
                setSelectedTool(null);
                setRfiSession(null);
                setRfiAnalysis(null);
                setRfiResult(null);
                setRfiFiles([]);
              }}
              className="bg-orange-500 text-white px-8 py-3 rounded-lg font-medium hover:bg-orange-600 transition-colors"
            >
              {embedded.isEmbedded ? "Import More" : "Import Another Project"}
            </button>
          </div>
        );

      default:
        return null;
    }
  };

  return (
    <div className="min-h-screen">
      {!embedded.isEmbedded && (
        <Header isAuthenticated={isAuthenticated} onLogout={handleLogout} />
      )}

      {isAuthenticated && step !== "auth" && step !== "complete" && (
        <div className="bg-white border-b border-gray-200">
          <div className="max-w-4xl mx-auto">
            <StepIndicator currentStep={step} isEmbedded={embedded.isEmbedded} selectedTool={selectedTool} />
          </div>
        </div>
      )}

      <main className={`max-w-2xl mx-auto px-6 ${embedded.isEmbedded ? "py-4" : "py-8"}`}>
        {/* Show project context when embedded */}
        {embedded.isEmbedded && project && step !== "auth" && step !== "complete" && (
          <div className="text-sm text-gray-500 mb-4">
            {company?.name} &rsaquo; {project.name}
          </div>
        )}

        {autoSelectingProject && (
          <div className="flex items-center justify-center py-12">
            <div className="text-center">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500 mx-auto mb-4"></div>
              <p className="text-gray-600">Loading project...</p>
              <p className="text-xs text-gray-400 mt-2">This may take up to a minute for large projects.</p>
            </div>
          </div>
        )}

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

        {!autoSelectingProject && (
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            {renderStepContent()}
          </div>
        )}
      </main>
    </div>
  );
}
