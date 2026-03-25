import { useState, useEffect } from "react";

export interface EmbeddedContext {
  /** Whether the app is running inside Procore's iframe */
  isEmbedded: boolean;
  /** Procore project ID from URL params (parameter interpolation) */
  projectId: number | null;
  /** Procore company ID from URL params (parameter interpolation) */
  companyId: number | null;
  /** Raw URL params for debugging embedded context */
  rawParams: Record<string, string>;
}

/**
 * Detects whether the app is embedded in Procore's iframe.
 *
 * Procore passes parameters via URL interpolation:
 *   ?procore_project_id={project_id}&procore_company_id={company_id}
 *
 * We detect embedded mode when either:
 *   1. Both procore_project_id and procore_company_id are in the URL, OR
 *   2. window.parent !== window (we're in an iframe)
 */
export function useEmbeddedContext(): EmbeddedContext {
  const [context, setContext] = useState<EmbeddedContext>({
    isEmbedded: false,
    projectId: null,
    companyId: null,
    rawParams: {},
  });

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const projectId = params.get("procore_project_id");
    const companyId = params.get("procore_company_id");
    const inIframe = window.parent !== window;

    // Capture all URL params for debugging
    const rawParams: Record<string, string> = {};
    params.forEach((value, key) => {
      rawParams[key] = value;
    });

    const hasParams = projectId !== null && companyId !== null;

    setContext({
      isEmbedded: hasParams || inIframe,
      projectId: projectId ? Number(projectId) : null,
      companyId: companyId ? Number(companyId) : null,
      rawParams,
    });
  }, []);

  return context;
}
