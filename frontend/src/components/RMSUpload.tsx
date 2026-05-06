"use client";

import { useState } from "react";
import { FileUpload } from "./FileUpload";
import { rms } from "@/lib/api";
import type { RMSSession } from "@/types";

interface RMSUploadProps {
  onUploadComplete: (session: RMSSession) => void;
  onBack?: () => void;
}

export function RMSUpload({ onUploadComplete, onBack }: RMSUploadProps) {
  const [registerReportFile, setRegisterReportFile] = useState<File | null>(null);
  const [reportFile, setReportFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [parseResult, setParseResult] = useState<RMSSession | null>(null);
  const [error, setError] = useState<string | null>(null);

  const canUpload = registerReportFile !== null && reportFile !== null;

  const handleUpload = async () => {
    if (!canUpload) return;

    setUploading(true);
    setError(null);

    try {
      const session = await rms.upload(
        registerReportFile!,
        reportFile || undefined,
      );

      if (session.errors.length > 0 && session.submittal_count === 0) {
        setError(`Parse failed: ${session.errors.join("; ")}`);
        return;
      }

      setParseResult(session);
      // Hand the parsed session up immediately so the parent can show the
      // folder picker beneath this component without an extra click.
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
          Upload both RMS export files below. The <strong>Submittal Register</strong> provides
          the master submittal list; the <strong>Transmittal Log</strong> adds revisions, dates,
          and historical QA codes.
        </p>
      </div>

      <div className="space-y-4">
        <FileUpload
          label="Submittal Register (Required)"
          description="All submittals with classifications, paragraph references, and status codes."
          accept=".csv"
          file={registerReportFile}
          onFileSelect={(f) => { setRegisterReportFile(f); setParseResult(null); }}
        />

        <FileUpload
          label="Transmittal Log (Required)"
          description="Adds revisions, dates, and historical QA codes for all transmittals"
          accept=".csv"
          file={reportFile}
          onFileSelect={(f) => { setReportFile(f); setParseResult(null); }}
        />
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* Parse summary */}
      {parseResult && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 space-y-2">
          <p className="text-sm font-medium text-green-800">
            Parsed {parseResult.submittal_count} submittals
          </p>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-600">Spec Sections</span>
              <span className="font-medium text-green-700">{parseResult.spec_section_count}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">Revisions</span>
              <span className="font-medium text-green-700">{parseResult.revision_count}</span>
            </div>
          </div>
          {parseResult.warnings.length > 0 && (
            <div className="text-xs text-yellow-700 mt-2">
              {parseResult.warnings.map((w, i) => <p key={i}>{w}</p>)}
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      {!parseResult && (
        <div className="flex gap-4">
          {onBack && (
            <button
              onClick={onBack}
              className="flex-1 py-3 px-4 rounded-lg font-medium border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors"
            >
              Back
            </button>
          )}
          <button
            onClick={handleUpload}
            disabled={!canUpload || uploading}
            className={`
              flex-1 py-3 px-4 rounded-lg font-medium transition-colors flex items-center justify-center gap-2
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
      )}
    </div>
  );
}
