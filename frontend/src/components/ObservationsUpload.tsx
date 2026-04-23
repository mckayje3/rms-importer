"use client";

import { useState, useRef } from "react";
import { observations } from "@/lib/api";
import type { ObservationsSession } from "@/types";

interface ObservationsUploadProps {
  onUploadComplete: (session: ObservationsSession) => void;
  onBack: () => void;
}

export function ObservationsUpload({ onUploadComplete, onBack }: ObservationsUploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [parseResult, setParseResult] = useState<ObservationsSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleUpload = async () => {
    if (!file) return;

    setUploading(true);
    setError(null);

    try {
      const session = await observations.upload(file);

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
    <div className="space-y-5">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Deficiency Items CSV
        </label>
        <p className="text-xs text-gray-500 mb-2">
          RMS QAQC Deficiency Items export. Includes QA and QC deficiency items.
        </p>
        <div
          className={`border-2 border-dashed rounded-lg p-4 text-center cursor-pointer transition-colors ${
            file ? "border-green-300 bg-green-50" : "border-gray-300 hover:border-orange-300"
          }`}
          onClick={() => fileRef.current?.click()}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".csv"
            onChange={(e) => {
              const selected = e.target.files?.[0];
              if (selected) {
                setFile(selected);
                setError(null);
                setParseResult(null);
              }
            }}
            className="hidden"
          />
          {file ? (
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-green-700">{file.name}</span>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setFile(null);
                  setParseResult(null);
                  if (fileRef.current) fileRef.current.value = "";
                }}
                className="text-xs text-gray-400 hover:text-gray-600"
              >
                Remove
              </button>
            </div>
          ) : (
            <p className="text-sm text-gray-400">Click to select CSV</p>
          )}
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {parseResult && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 space-y-2">
          <p className="text-sm font-medium text-green-800">Parsed successfully</p>
          {parseResult.project_name && (
            <p className="text-xs text-gray-600">{parseResult.project_name}</p>
          )}
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-600">Total</span>
              <span className="font-medium text-green-700">{parseResult.total_count}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">Open</span>
              <span className="font-medium text-orange-600">{parseResult.open_count}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">Closed</span>
              <span className="font-medium text-green-700">{parseResult.closed_count}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">Locations</span>
              <span className="font-medium text-green-700">{parseResult.locations.length}</span>
            </div>
          </div>
          {parseResult.warnings.length > 0 && (
            <div className="text-xs text-yellow-700 mt-2">
              {parseResult.warnings.map((w, i) => <p key={i}>{w}</p>)}
            </div>
          )}
        </div>
      )}

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
                Parsing...
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
