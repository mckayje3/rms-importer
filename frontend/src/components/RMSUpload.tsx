"use client";

import { useState } from "react";
import { FileUpload } from "./FileUpload";
import { rms } from "@/lib/api";
import type { RMSSession } from "@/types";

interface RMSUploadProps {
  onUploadComplete: (session: RMSSession) => void;
}

export function RMSUpload({ onUploadComplete }: RMSUploadProps) {
  const [registerFile, setRegisterFile] = useState<File | null>(null);
  const [assignmentsFile, setAssignmentsFile] = useState<File | null>(null);
  const [reportFile, setReportFile] = useState<File | null>(null);
  const [registerReportFile, setRegisterReportFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hasRegisterReport = registerReportFile !== null;
  const canUpload = hasRegisterReport || registerFile !== null;

  const handleUpload = async () => {
    if (!canUpload) return;

    setUploading(true);
    setError(null);

    try {
      const session = await rms.upload(
        hasRegisterReport ? undefined : registerFile || undefined,
        hasRegisterReport ? undefined : assignmentsFile || undefined,
        reportFile || undefined,
        registerReportFile || undefined,
      );
      onUploadComplete(session);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
      console.error(err);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <h3 className="text-sm font-medium text-blue-800 mb-2">
          RMS Export Files
        </h3>
        <p className="text-sm text-blue-700">
          Upload RMS export files below. Use the <strong>Register Report</strong> (recommended)
          or the individual Register + Assignments files. The Transmittal Report adds
          revision tracking and historical QA codes.
        </p>
      </div>

      <div className="space-y-4">
        {/* Register Report — recommended single-file option */}
        <FileUpload
          label="Submittal Register Report (Recommended)"
          description="Single file with all submittals, classifications, and paragraph references. Replaces Register + Assignments."
          accept=".csv"
          file={registerReportFile}
          onFileSelect={(f) => {
            setRegisterReportFile(f);
            if (f) {
              // Clear individual files when report is selected
              setRegisterFile(null);
              setAssignmentsFile(null);
            }
          }}
        />

        {/* Divider */}
        {!hasRegisterReport && (
          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-gray-300" />
            </div>
            <div className="relative flex justify-center text-sm">
              <span className="px-2 bg-white text-gray-500">or use individual files</span>
            </div>
          </div>
        )}

        {/* Individual files — hidden when Register Report is selected */}
        {!hasRegisterReport && (
          <>
            <FileUpload
              label="Submittal Register (Required if no Register Report)"
              description="Contains all submittals with status, dates, and QA/QC codes"
              file={registerFile}
              onFileSelect={setRegisterFile}
            />

            <FileUpload
              label="Submittal Assignments (Optional)"
              description="Adds Info field (GA/FIO/S) classification"
              file={assignmentsFile}
              onFileSelect={setAssignmentsFile}
            />
          </>
        )}

        <FileUpload
          label="Transmittal Report (Optional)"
          description="Adds revisions, dates, and historical QA codes for all transmittals"
          accept=".csv,.xlsx,.xls"
          file={reportFile}
          onFileSelect={setReportFile}
        />
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      <button
        onClick={handleUpload}
        disabled={!canUpload || uploading}
        className={`
          w-full py-3 px-4 rounded-lg font-medium transition-colors flex items-center justify-center gap-2
          ${
            canUpload && !uploading
              ? "bg-orange-500 text-white hover:bg-orange-600"
              : "bg-gray-200 text-gray-500 cursor-not-allowed"
          }
        `}
      >
        {uploading ? (
          <>
            <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
            Uploading & Parsing...
          </>
        ) : (
          "Upload & Parse Files"
        )}
      </button>
    </div>
  );
}
