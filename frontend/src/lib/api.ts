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
    registerFile: File,
    assignmentsFile: File,
    transmittalFile: File,
    reportFile?: File
  ): Promise<RMSSession> => {
    const formData = new FormData();
    formData.append("submittal_register", registerFile);
    formData.append("submittal_assignments", assignmentsFile);
    formData.append("transmittal_log", transmittalFile);
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
    options: { creates: boolean; updates: boolean; files: boolean }
  ): Promise<SyncExecuteResponse> => {
    return fetchAPI(`/sync/projects/${projectId}/execute`, {
      method: "POST",
      headers: {
        "X-Company-Id": String(companyId),
      },
      body: JSON.stringify({
        session_id: sessionId,
        apply_creates: options.creates,
        apply_updates: options.updates,
        apply_file_uploads: options.files,
      }),
    });
  },
};

// Health check
export const health = async (): Promise<{ status: string }> => {
  return fetchAPI("/health");
};

export { APIError };
