"use client";

import { useState, useCallback } from "react";
import { FileUpload } from "./FileUpload";
import { ContractorMatchReview } from "./ContractorMatchReview";
import { rms } from "@/lib/api";
import type {
  MatchContractorsResponse,
  ProcoreVendor,
  ContractorMapping as ContractorMappingType,
} from "@/types";

type Step = "upload" | "matching" | "review";

interface ContractorMappingProps {
  sessionId: string;
  projectId: number;
  companyId: number;
  authSession: string;
  onComplete: () => void;
  onSkip: () => void;
}

export function ContractorMapping({
  sessionId,
  projectId,
  companyId,
  authSession,
  onComplete,
  onSkip,
}: ContractorMappingProps) {
  const [step, setStep] = useState<Step>("upload");
  const [mappingFile, setMappingFile] = useState<File | null>(null);
  const [existingMapping, setExistingMapping] = useState<ContractorMappingType | null>(null);
  const [matchResults, setMatchResults] = useState<MatchContractorsResponse | null>(null);
  const [vendors, setVendors] = useState<ProcoreVendor[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Check for existing mapping on mount
  const checkExistingMapping = useCallback(async () => {
    try {
      const mapping = await rms.getContractorMapping(sessionId);
      if (mapping.has_mapping) {
        setExistingMapping(mapping);
      }
    } catch {
      // No existing mapping
    }
  }, [sessionId]);

  // Download template
  const handleDownloadTemplate = () => {
    const url = rms.downloadContractorTemplate(sessionId);
    window.open(url, "_blank");
  };

  // Upload mapping file
  const handleUpload = async () => {
    if (!mappingFile) return;

    setLoading(true);
    setError(null);

    try {
      await rms.uploadContractorMapping(sessionId, mappingFile);
      await runMatching();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setLoading(false);
    }
  };

  // Run matching against Procore Directory
  const runMatching = async () => {
    setStep("matching");
    setLoading(true);
    setError(null);

    try {
      // Fetch vendors first
      const vendorResponse = await rms.getVendors(
        sessionId,
        projectId,
        companyId,
        authSession
      );
      setVendors(vendorResponse.vendors);

      // Run matching
      const results = await rms.matchContractors(
        sessionId,
        projectId,
        companyId,
        authSession
      );
      setMatchResults(results);
      setStep("review");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Matching failed");
      setStep("upload");
    } finally {
      setLoading(false);
    }
  };

  // Use existing mapping
  const handleUseExisting = async () => {
    await runMatching();
  };

  if (step === "matching") {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500 mb-4"></div>
        <p className="text-gray-600">Matching contractors to Procore Directory...</p>
        <p className="text-sm text-gray-400 mt-2">
          This may take a moment for large directories.
        </p>
      </div>
    );
  }

  if (step === "review" && matchResults) {
    return (
      <ContractorMatchReview
        sessionId={sessionId}
        matchResults={matchResults}
        vendors={vendors}
        onConfirmAll={onComplete}
        onBack={() => setStep("upload")}
      />
    );
  }

  // Upload step
  return (
    <div className="space-y-6">
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <h3 className="text-sm font-medium text-blue-800 mb-2">
          Contractor Mapping (Optional)
        </h3>
        <p className="text-sm text-blue-700">
          Map spec sections to contractors so submittals can be assigned to the
          correct Responsible Contractor in Procore. If you skip this step,
          submittals will be created without contractor assignments.
        </p>
      </div>

      {existingMapping && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4">
          <h3 className="text-sm font-medium text-green-800 mb-2">
            Existing Mapping Found
          </h3>
          <p className="text-sm text-green-700 mb-3">
            A contractor mapping with {existingMapping.total_sections} sections
            was previously uploaded.
          </p>
          <button
            onClick={handleUseExisting}
            className="px-4 py-2 text-sm font-medium text-green-700 bg-green-100 rounded-md hover:bg-green-200"
          >
            Use Existing Mapping
          </button>
        </div>
      )}

      <div className="bg-white border border-gray-200 rounded-lg p-6">
        <h3 className="text-lg font-medium text-gray-900 mb-4">
          Step 1: Download Template
        </h3>
        <p className="text-sm text-gray-600 mb-4">
          Download a CSV template pre-filled with all spec sections from your
          RMS data. Fill in the contractor name for each section.
        </p>
        <button
          onClick={handleDownloadTemplate}
          className="px-4 py-2 text-sm font-medium text-orange-600 bg-orange-50 rounded-md hover:bg-orange-100 border border-orange-200"
        >
          Download Template (CSV)
        </button>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-6">
        <h3 className="text-lg font-medium text-gray-900 mb-4">
          Step 2: Upload Completed Mapping
        </h3>
        <p className="text-sm text-gray-600 mb-4">
          Upload your completed mapping file (CSV or Excel). The app will
          automatically match contractor names to your Procore Directory.
        </p>

        <FileUpload
          label="Contractor Mapping"
          description="CSV or Excel with Section and Contractor columns"
          file={mappingFile}
          onFileSelect={setMappingFile}
          accept=".csv,.xlsx,.xls"
        />

        {error && (
          <div className="mt-4 bg-red-50 border border-red-200 rounded-lg p-4">
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}

        <button
          onClick={handleUpload}
          disabled={!mappingFile || loading}
          className={`mt-4 w-full py-3 px-4 rounded-lg font-medium transition-colors flex items-center justify-center gap-2 ${
            mappingFile && !loading
              ? "bg-orange-500 text-white hover:bg-orange-600"
              : "bg-gray-200 text-gray-500 cursor-not-allowed"
          }`}
        >
          {loading ? (
            <>
              <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
              Processing...
            </>
          ) : (
            "Upload & Match"
          )}
        </button>
      </div>

      <div className="flex items-center justify-between pt-4 border-t border-gray-200">
        <button
          onClick={onSkip}
          className="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-900"
        >
          Skip This Step
        </button>
        <p className="text-sm text-gray-400">
          You can add contractors later in Procore
        </p>
      </div>
    </div>
  );
}
