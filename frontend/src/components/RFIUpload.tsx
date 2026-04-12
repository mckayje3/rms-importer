"use client";

import { useState, useRef } from "react";
import { rfi as rfiApi } from "@/lib/api";
import type { RFISession } from "@/types";

interface RFIUploadProps {
  onUploadComplete: (session: RFISession) => void;
  onBack: () => void;
}

export function RFIUpload({ onUploadComplete, onBack }: RFIUploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [parseResult, setParseResult] = useState<RFISession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (selected) {
      setFile(selected);
      setError(null);
      setParseResult(null);
    }
  };

  const handleUpload = async () => {
    if (!file) return;

    setUploading(true);
    setError(null);

    try {
      const session = await rfiApi.upload(file);

      if (session.errors.length > 0 && session.total_count === 0) {
        setError(`Parse failed: ${session.errors.join("; ")}`);
        return;
      }

      setParseResult(session);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* File input */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          RFI Report CSV
        </label>
        <p className="text-xs text-gray-500 mb-3">
          Export the full &quot;All Requests for Information&quot; report from RMS as CSV.
          This file contains the complete question and response text for each RFI.
        </p>
        <div
          className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors ${
            file ? "border-green-300 bg-green-50" : "border-gray-300 hover:border-orange-300"
          }`}
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            onChange={handleFileChange}
            className="hidden"
          />
          {file ? (
            <div>
              <p className="text-sm font-medium text-green-700">{file.name}</p>
              <p className="text-xs text-green-600 mt-1">
                {(file.size / 1024).toFixed(1)} KB
              </p>
            </div>
          ) : (
            <div>
              <svg className="w-8 h-8 mx-auto text-gray-400 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
              <p className="text-sm text-gray-500">Click to select RFI Report CSV</p>
            </div>
          )}
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* Parse summary */}
      {parseResult && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 space-y-2">
          <p className="text-sm font-medium text-green-800">
            Parsed {parseResult.total_count} RFIs
          </p>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-600">Answered</span>
              <span className="font-medium text-green-700">{parseResult.answered_count}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">Outstanding</span>
              <span className="font-medium text-yellow-700">{parseResult.outstanding_count}</span>
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
      <div className="flex gap-4">
        <button
          onClick={onBack}
          className="flex-1 py-3 px-4 rounded-lg font-medium border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors"
        >
          Back
        </button>
        {!parseResult ? (
          <button
            onClick={handleUpload}
            disabled={!file || uploading}
            className="flex-1 py-3 px-4 rounded-lg font-medium bg-orange-500 text-white hover:bg-orange-600 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {uploading ? (
              <>
                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
                Parsing RFIs...
              </>
            ) : (
              "Upload & Parse"
            )}
          </button>
        ) : (
          <button
            onClick={() => onUploadComplete(parseResult)}
            className="flex-1 py-3 px-4 rounded-lg font-medium bg-orange-500 text-white hover:bg-orange-600 transition-colors"
          >
            Continue
          </button>
        )}
      </div>
    </div>
  );
}
