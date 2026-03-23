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
  const [transmittalFile, setTransmittalFile] = useState<File | null>(null);
  const [reportFile, setReportFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const allFilesSelected = registerFile && assignmentsFile && transmittalFile && reportFile;

  const handleUpload = async () => {
    if (!allFilesSelected) return;

    setUploading(true);
    setError(null);

    try {
      const session = await rms.upload(
        registerFile,
        assignmentsFile,
        transmittalFile,
        reportFile
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
          RMS Export Files Required
        </h3>
        <p className="text-sm text-blue-700">
          Export these four files from RMS (Resident Management System) and upload them below.
          All files should be in Excel format (.xlsx).
        </p>
      </div>

      <div className="space-y-4">
        <FileUpload
          label="Submittal Register"
          description="Contains all submittals with status, dates, and QA/QC codes"
          file={registerFile}
          onFileSelect={setRegisterFile}
        />

        <FileUpload
          label="Submittal Assignments"
          description="Contains submittal assignments and schedule activities"
          file={assignmentsFile}
          onFileSelect={setAssignmentsFile}
        />

        <FileUpload
          label="Transmittal Log"
          description="In RMS, click Transmittal Log then select Completed Transmittals before downloading"
          file={transmittalFile}
          onFileSelect={setTransmittalFile}
        />

        <FileUpload
          label="Transmittal Report"
          description="In RMS, go to Contract Reports > Submit > double-click Transmittal Log > Preview > Save as CSV"
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
        disabled={!allFilesSelected || uploading}
        className={`
          w-full py-3 px-4 rounded-lg font-medium transition-colors flex items-center justify-center gap-2
          ${
            allFilesSelected && !uploading
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
