// API client for backend communication

import type {
  ProcoreCompany,
  ProcoreProject,
  ProcoreStats,
  RMSSession,
  AnalyzeResponse,
  ImportMode,
  MatchContractorsResponse,
  ProcoreVendor,
  ContractorMapping,
  BaselineInfo,
  SyncAnalysisResponse,
  SyncExecuteResponse,
  ProjectDiscovery,
  ProjectConfig,
  ProjectConfigData,
  FileFilterResponse,
  FileJobStatus,
  RFISession,
  RMSRFI,
  RFIAnalyzeResponse,
  RFIExecuteResponse,
  RFIJobStatus,
  DailyLogSession,
  DailyLogAnalyzeResponse,
  DailyLogExecuteResponse,
  DailyLogJobStatus,
} from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

class APIError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
    this.name = "APIError";
  }
}

async function fetchAPI<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  // Include auth session header if available
  const authSession = typeof window !== "undefined"
    ? sessionStorage.getItem("auth_session")
    : null;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(authSession ? { "X-Auth-Session": authSession } : {}),
    ...(options.headers as Record<string, string> || {}),
  };

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    credentials: "include",
    headers,
  });

  if (!response.ok) {
    const error = await response.text();
    throw new APIError(response.status, error);
  }

  return response.json();
}

// Auth endpoints
export const auth = {
  getLoginUrl: () => `${API_BASE}/auth/login`,

  logout: async () => {
    await fetchAPI("/auth/logout", { method: "POST" });
  },

  refresh: async () => {
    await fetchAPI("/auth/refresh", { method: "POST" });
  },
};

// Project endpoints
export const projects = {
  getCompanies: async (): Promise<ProcoreCompany[]> => {
    return fetchAPI("/projects/companies");
  },

  getProjects: async (companyId: number): Promise<ProcoreProject[]> => {
    return fetchAPI(`/projects/companies/${companyId}/projects`);
  },

  getStats: async (projectId: number, companyId: number): Promise<ProcoreStats> => {
    return fetchAPI(`/projects/projects/${projectId}/stats?company_id=${companyId}`);
  },
};

// RMS endpoints
export const rms = {
  upload: async (
    registerReportFile: File,
    reportFile?: File,
  ): Promise<RMSSession> => {
    const formData = new FormData();
    formData.append("register_report", registerReportFile);
    if (reportFile) {
      formData.append("transmittal_report", reportFile);
    }

    const response = await fetch(`${API_BASE}/rms/upload`, {
      method: "POST",
      credentials: "include",
      body: formData,
    });

    if (!response.ok) {
      const error = await response.text();
      throw new APIError(response.status, error);
    }

    return response.json();
  },

  getSession: async (sessionId: string): Promise<RMSSession> => {
    return fetchAPI(`/rms/session/${sessionId}`);
  },

  deleteSession: async (sessionId: string): Promise<void> => {
    await fetchAPI(`/rms/session/${sessionId}`, { method: "DELETE" });
  },

  // Contractor mapping
  downloadContractorTemplate: (sessionId: string): string => {
    return `${API_BASE}/rms/session/${sessionId}/contractor-template`;
  },

  uploadContractorMapping: async (
    sessionId: string,
    file: File
  ): Promise<{ status: string; total_sections: number; sections: string[] }> => {
    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch(
      `${API_BASE}/rms/session/${sessionId}/contractor-mapping`,
      {
        method: "POST",
        credentials: "include",
        body: formData,
      }
    );

    if (!response.ok) {
      const error = await response.text();
      throw new APIError(response.status, error);
    }

    return response.json();
  },

  getContractorMapping: async (sessionId: string): Promise<ContractorMapping> => {
    return fetchAPI(`/rms/session/${sessionId}/contractor-mapping`);
  },

  matchContractors: async (
    sessionId: string,
    projectId: number,
    companyId: number,
    authSession: string
  ): Promise<MatchContractorsResponse> => {
    const response = await fetch(
      `${API_BASE}/rms/session/${sessionId}/match-contractors`,
      {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-Auth-Session": authSession,
        },
        body: JSON.stringify({
          project_id: projectId,
          company_id: companyId,
        }),
      }
    );

    if (!response.ok) {
      const error = await response.text();
      throw new APIError(response.status, error);
    }

    return response.json();
  },

  confirmMatch: async (
    sessionId: string,
    section: string,
    vendorId: number
  ): Promise<{ status: string; section: string; vendor_id: number; vendor_name: string | null }> => {
    return fetchAPI(`/rms/session/${sessionId}/confirm-match`, {
      method: "POST",
      body: JSON.stringify({ section, vendor_id: vendorId }),
    });
  },

  getVendors: async (
    sessionId: string,
    projectId: number,
    companyId: number,
    authSession: string
  ): Promise<{ count: number; vendors: ProcoreVendor[] }> => {
    const response = await fetch(
      `${API_BASE}/rms/session/${sessionId}/vendors?project_id=${projectId}&company_id=${companyId}`,
      {
        method: "GET",
        credentials: "include",
        headers: {
          "X-Auth-Session": authSession,
        },
      }
    );

    if (!response.ok) {
      const error = await response.text();
      throw new APIError(response.status, error);
    }

    return response.json();
  },
};

// Submittal endpoints
export const submittals = {
  analyze: async (
    projectId: number,
    sessionId: string
  ): Promise<AnalyzeResponse> => {
    return fetchAPI(`/submittals/projects/${projectId}/analyze`, {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    });
  },

  import: async (
    projectId: number,
    sessionId: string,
    mode: ImportMode,
    selectedKeys?: string[]
  ): Promise<{ imported: number; updated: number; errors: string[] }> => {
    return fetchAPI(`/submittals/projects/${projectId}/import`, {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        mode,
        selected_keys: selectedKeys,
      }),
    });
  },
};

// Sync endpoints
export const sync = {
  getBaseline: async (projectId: number): Promise<BaselineInfo> => {
    return fetchAPI(`/sync/projects/${projectId}/baseline`);
  },

  analyze: async (
    projectId: number,
    sessionId: string,
    companyId: number,
    fileList: string[] = []
  ): Promise<SyncAnalysisResponse> => {
    return fetchAPI(`/sync/projects/${projectId}/analyze`, {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        project_id: projectId,
        company_id: companyId,
        file_list: fileList,
      }),
    });
  },

  execute: async (
    projectId: number,
    sessionId: string,
    companyId: number,
    options: { creates: boolean; updates: boolean; dates: boolean },
    files: File[] = []
  ): Promise<SyncExecuteResponse> => {
    const authSession = typeof window !== "undefined"
      ? sessionStorage.getItem("auth_session")
      : null;

    const formData = new FormData();
    formData.append("request_json", JSON.stringify({
      session_id: sessionId,
      apply_creates: options.creates,
      apply_updates: options.updates,
      apply_date_updates: options.dates,
    }));
    for (const file of files) {
      formData.append("files", file);
    }

    const response = await fetch(`${API_BASE}/sync/projects/${projectId}/execute-all`, {
      method: "POST",
      credentials: "include",
      headers: {
        ...(authSession ? { "X-Auth-Session": authSession } : {}),
        "X-Company-Id": String(companyId),
      },
      body: formData,
    });

    if (!response.ok) {
      const error = await response.text();
      throw new APIError(response.status, error);
    }

    return response.json();
  },

  bootstrap: async (
    projectId: number,
    sessionId: string,
    companyId: number
  ): Promise<{ status: string; matched: number; unmatched: number; total_rms: number; total_procore: number }> => {
    return fetchAPI(`/sync/projects/${projectId}/bootstrap`, {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        company_id: companyId,
      }),
    });
  },

  filterFiles: async (
    projectId: number,
    sessionId: string,
    filenames: string[]
  ): Promise<FileFilterResponse> => {
    return fetchAPI(`/sync/projects/${projectId}/filter-files`, {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        filenames,
      }),
    });
  },

  getFileJobStatus: async (
    projectId: number,
    jobId: string
  ): Promise<FileJobStatus> => {
    return fetchAPI(`/sync/projects/${projectId}/file-jobs/${jobId}`);
  },

  listJobs: async (
    projectId: number,
    limit: number = 5
  ): Promise<{ project_id: number; jobs: FileJobStatus[] }> => {
    return fetchAPI(`/sync/projects/${projectId}/file-jobs?limit=${limit}`);
  },
};

// Setup endpoints
export const setup = {
  discover: async (projectId: number, companyId: number): Promise<ProjectDiscovery> => {
    return fetchAPI(`/setup/projects/${projectId}/discover?company_id=${companyId}`);
  },

  getConfig: async (projectId: number): Promise<ProjectConfig> => {
    return fetchAPI(`/setup/projects/${projectId}/config`);
  },

  saveConfig: async (
    projectId: number,
    companyId: number,
    configData: ProjectConfigData
  ): Promise<{ status: string; project_id: number }> => {
    return fetchAPI(`/setup/projects/${projectId}/config`, {
      method: "POST",
      body: JSON.stringify({
        company_id: String(companyId),
        config_data: configData,
      }),
    });
  },

  deleteConfig: async (projectId: number): Promise<{ status: string }> => {
    return fetchAPI(`/setup/projects/${projectId}/config`, {
      method: "DELETE",
    });
  },
};

// RFI endpoints
export const rfi = {
  upload: async (file: File): Promise<RFISession> => {
    const authSession = typeof window !== "undefined"
      ? sessionStorage.getItem("auth_session")
      : null;

    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch(`${API_BASE}/rfi/upload`, {
      method: "POST",
      credentials: "include",
      headers: {
        ...(authSession ? { "X-Auth-Session": authSession } : {}),
      },
      body: formData,
    });

    if (!response.ok) {
      const error = await response.text();
      throw new APIError(response.status, error);
    }

    return response.json();
  },

  listItems: async (sessionId: string): Promise<RMSRFI[]> => {
    return fetchAPI(`/rfi/session/${sessionId}/items`);
  },

  analyze: async (
    projectId: number,
    sessionId: string,
    companyId: number
  ): Promise<RFIAnalyzeResponse> => {
    return fetchAPI(`/rfi/projects/${projectId}/analyze`, {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        company_id: companyId,
      }),
    });
  },

  execute: async (
    projectId: number,
    sessionId: string,
    companyId: number,
    options: {
      creates: boolean;
      replies: boolean;
      responseUpdates: boolean;
      responseUpdateItems?: { rfi_number: string; number: number; procore_rfi_id: number; response_body: string; date_answered: string | null }[];
    }
  ): Promise<RFIExecuteResponse> => {
    return fetchAPI(`/rfi/projects/${projectId}/execute`, {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        company_id: companyId,
        apply_creates: options.creates,
        apply_replies: options.replies,
        apply_response_updates: options.responseUpdates,
        response_updates: options.responseUpdateItems || [],
      }),
    });
  },

  executeWithFiles: async (
    projectId: number,
    sessionId: string,
    companyId: number,
    options: {
      creates: boolean;
      replies: boolean;
      responseUpdates: boolean;
      responseUpdateItems?: { rfi_number: string; number: number; procore_rfi_id: number; response_body: string; date_answered: string | null }[];
    },
    rfiFiles: File[]
  ): Promise<RFIExecuteResponse> => {
    const authSession = typeof window !== "undefined"
      ? sessionStorage.getItem("auth_session")
      : null;

    const formData = new FormData();
    formData.append("request_json", JSON.stringify({
      session_id: sessionId,
      company_id: companyId,
      apply_creates: options.creates,
      apply_replies: options.replies,
      apply_response_updates: options.responseUpdates,
      response_updates: options.responseUpdateItems || [],
    }));
    for (const file of rfiFiles) {
      formData.append("rfi_files", file);
    }

    const response = await fetch(`${API_BASE}/rfi/projects/${projectId}/execute-with-files`, {
      method: "POST",
      credentials: "include",
      headers: {
        ...(authSession ? { "X-Auth-Session": authSession } : {}),
      },
      body: formData,
    });

    if (!response.ok) {
      const error = await response.text();
      throw new APIError(response.status, error);
    }

    return response.json();
  },

  getJobStatus: async (jobId: string): Promise<RFIJobStatus> => {
    return fetchAPI(`/rfi/jobs/${jobId}`);
  },

  filterFiles: async (
    projectId: number,
    filenames: string[]
  ): Promise<{ new_files: string[]; already_attached: string[]; unmapped_files: string[]; total_checked: number }> => {
    return fetchAPI(`/rfi/projects/${projectId}/filter-files`, {
      method: "POST",
      body: JSON.stringify({ filenames }),
    });
  },
};

// Daily Logs endpoints
export const dailyLogs = {
  upload: async (
    equipmentFile?: File,
    laborFile?: File,
    narrativeFile?: File,
  ): Promise<DailyLogSession> => {
    const authSession = typeof window !== "undefined"
      ? sessionStorage.getItem("auth_session")
      : null;

    const formData = new FormData();
    if (equipmentFile) formData.append("equipment_file", equipmentFile);
    if (laborFile) formData.append("labor_file", laborFile);
    if (narrativeFile) formData.append("narrative_file", narrativeFile);

    const response = await fetch(`${API_BASE}/daily-logs/upload`, {
      method: "POST",
      credentials: "include",
      headers: {
        ...(authSession ? { "X-Auth-Session": authSession } : {}),
      },
      body: formData,
    });

    if (!response.ok) {
      const error = await response.text();
      throw new APIError(response.status, error);
    }

    return response.json();
  },

  analyze: async (
    projectId: number,
    sessionId: string,
    companyId: number
  ): Promise<DailyLogAnalyzeResponse> => {
    return fetchAPI(`/daily-logs/projects/${projectId}/analyze`, {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        company_id: companyId,
      }),
    });
  },

  execute: async (
    projectId: number,
    sessionId: string,
    companyId: number,
    options: {
      equipment: boolean;
      labor: boolean;
      narratives: boolean;
      vendorMap: Record<string, number | null>;
    }
  ): Promise<DailyLogExecuteResponse> => {
    return fetchAPI(`/daily-logs/projects/${projectId}/execute`, {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        company_id: companyId,
        apply_equipment: options.equipment,
        apply_labor: options.labor,
        apply_narratives: options.narratives,
        vendor_map: options.vendorMap,
      }),
    });
  },

  getJobStatus: async (jobId: string): Promise<DailyLogJobStatus> => {
    return fetchAPI(`/daily-logs/jobs/${jobId}`);
  },
};

// Observations (QAQC Deficiencies) endpoints
export const observations = {
  upload: async (file: File): Promise<import("@/types").ObservationsSession> => {
    const authSession = typeof window !== "undefined"
      ? sessionStorage.getItem("auth_session")
      : null;

    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch(`${API_BASE}/qaqc/upload`, {
      method: "POST",
      credentials: "include",
      headers: {
        ...(authSession ? { "X-Auth-Session": authSession } : {}),
      },
      body: formData,
    });

    if (!response.ok) {
      const error = await response.text();
      throw new APIError(response.status, error);
    }

    return response.json();
  },

  analyze: async (
    projectId: number,
    sessionId: string,
    companyId: number
  ): Promise<import("@/types").ObservationsAnalyzeResponse> => {
    return fetchAPI(`/qaqc/projects/${projectId}/analyze`, {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        company_id: companyId,
      }),
    });
  },

  execute: async (
    projectId: number,
    sessionId: string,
    companyId: number,
    options: {
      observationTypeId: number | null;
      createLocations: boolean;
      locationMap: Record<string, number | null>;
    }
  ): Promise<import("@/types").ObservationsExecuteResponse> => {
    return fetchAPI(`/qaqc/projects/${projectId}/execute`, {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        company_id: companyId,
        observation_type_id: options.observationTypeId,
        create_locations: options.createLocations,
        location_map: options.locationMap,
      }),
    });
  },

  getJobStatus: async (jobId: string): Promise<import("@/types").ObservationsJobStatus> => {
    return fetchAPI(`/qaqc/jobs/${jobId}`);
  },
};

// Health check
export const health = async (): Promise<{ status: string }> => {
  return fetchAPI("/health");
};

export { APIError };
