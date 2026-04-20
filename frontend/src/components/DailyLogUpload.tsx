"use client";

import { useState, useRef } from "react";
import { dailyLogs } from "@/lib/api";
import type { DailyLogSession } from "@/types";

interface DailyLogUploadProps {
  onUploadComplete: (session: DailyLogSession) => void;
  onBack: () => void;
}

export function DailyLogUpload({ onUploadComplete, onBack }: DailyLogUploadProps) {
  const [equipmentFile, setEquipmentFile] = useState<File | null>(null);
  const [laborFile, setLaborFile] = useState<File | null>(null);
  const [narrativeFile, setNarrativeFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [parseResult, setParseResult] = useState<DailyLogSession | null>(null);
  const [error, setError] = useState<string | null>(null);

  const equipRef = useRef<HTMLInputElement>(null);
  const laborRef = useRef<HTMLInputElement>(null);
  const narrRef = useRef<HTMLInputElement>(null);

  const hasFiles = equipmentFile || laborFile || narrativeFile;

  const handleUpload = async () => {
    if (!hasFiles) return;

    setUploading(true);
    setError(null);

    try {
      const session = await dailyLogs.upload(
        equipmentFile || undefined,
        laborFile || undefined,
        narrativeFile || undefined,
      );

      if (session.errors.length > 0 && session.equipment_count === 0 && session.labor_count === 0 && session.narrative_count === 0) {
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

  const fileSlot = (
    label: string,
    description: string,
    file: File | null,
    setFile: (f: File | null) => void,
    inputRef: React.RefObject<HTMLInputElement | null>,
  ) => (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      <p className="text-xs text-gray-500 mb-2">{description}</p>
      <div
        className={`border-2 border-dashed rounded-lg p-4 text-center cursor-pointer transition-colors ${
          file ? "border-green-300 bg-green-50" : "border-gray-300 hover:border-orange-300"
        }`}
        onClick={() => inputRef.current?.click()}
      >
        <input
          ref={inputRef}
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
                if (inputRef.current) inputRef.current.value = "";
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
  );

  return (
    <div className="space-y-5">
      {fileSlot(
        "QC Equipment Hours",
        "Equipment idle and operating hours by report date.",
        equipmentFile, setEquipmentFile, equipRef,
      )}

      {fileSlot(
        "QC Labor Hours",
        "Labor hours by employer and classification.",
        laborFile, setLaborFile, laborRef,
      )}

      {fileSlot(
        "QC Narratives",
        "QC narrative entries grouped by category.",
        narrativeFile, setNarrativeFile, narrRef,
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {parseResult && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 space-y-2">
          <p className="text-sm font-medium text-green-800">
            Parsed successfully
          </p>
          <div className="grid grid-cols-2 gap-2 text-sm">
            {parseResult.equipment_count > 0 && (
              <div className="flex justify-between">
                <span className="text-gray-600">Equipment</span>
                <span className="font-medium text-green-700">{parseResult.equipment_count}</span>
              </div>
            )}
            {parseResult.labor_count > 0 && (
              <div className="flex justify-between">
                <span className="text-gray-600">Labor</span>
                <span className="font-medium text-green-700">{parseResult.labor_count}</span>
              </div>
            )}
            {parseResult.narrative_count > 0 && (
              <div className="flex justify-between">
                <span className="text-gray-600">Narratives</span>
                <span className="font-medium text-green-700">{parseResult.narrative_count}</span>
              </div>
            )}
            <div className="flex justify-between">
              <span className="text-gray-600">Date range</span>
              <span className="font-medium text-green-700">{parseResult.date_count} days</span>
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
            disabled={!hasFiles || uploading}
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
