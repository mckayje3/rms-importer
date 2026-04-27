"use client";

import { useState, useRef, useCallback } from "react";
import { sync } from "@/lib/api";
import type { FileFilterResponse } from "@/types";

interface FolderPickerProps {
  projectId: number;
  rmsSessionId: string;
  selectedFiles: File[];
  filterResult: FileFilterResponse | null;
  onPick: (files: File[], filterResult: FileFilterResponse | null) => void;
}

export function FolderPicker({
  projectId,
  rmsSessionId,
  selectedFiles,
  filterResult,
  onPick,
}: FolderPickerProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isFiltering, setIsFiltering] = useState(false);
  const [showNewFiles, setShowNewFiles] = useState(false);
  const [error, setError] = useState<string>("");

  const handleFolderSelect = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || []);
      if (files.length === 0) return;

      const transmittalFiles = files.filter((f) =>
        f.name.startsWith("Transmittal ")
      );

      setError("");

      if (transmittalFiles.length === 0) {
        setError(
          `Found ${files.length} files but none match the "Transmittal ..." naming convention.`
        );
        onPick([], null);
        return;
      }

      setIsFiltering(true);
      try {
        const filenames = transmittalFiles.map((f) => f.name);
        const result = await sync.filterFiles(projectId, rmsSessionId, filenames);
        onPick(transmittalFiles, result);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to check files");
        onPick([], null);
      } finally {
        setIsFiltering(false);
      }
    },
    [projectId, rmsSessionId, onPick]
  );

  const handleClear = useCallback(() => {
    onPick([], null);
    setError("");
    if (inputRef.current) {
      inputRef.current.value = "";
    }
  }, [onPick]);

  const newCount = filterResult?.new_files.length ?? 0;
  const alreadyCount = filterResult?.already_uploaded.length ?? 0;
  const unmappedCount = filterResult?.unmapped_files.length ?? 0;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <input
          ref={inputRef}
          type="file"
          /* @ts-expect-error webkitdirectory is not in React types */
          webkitdirectory=""
          directory=""
          multiple
          onChange={handleFolderSelect}
          className="hidden"
          id="folder-picker"
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={isFiltering}
          className="px-4 py-2 text-sm font-medium text-white bg-purple-600 rounded-md
            hover:bg-purple-700 disabled:bg-gray-400 disabled:cursor-not-allowed
            transition-colors"
        >
          {isFiltering ? (
            <span className="flex items-center gap-2">
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Checking files...
            </span>
          ) : selectedFiles.length > 0 ? (
            "Change Folder"
          ) : (
            "Select RMS Files Folder"
          )}
        </button>

        {selectedFiles.length > 0 && (
          <button
            type="button"
            onClick={handleClear}
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            Clear
          </button>
        )}
      </div>

      {filterResult && (
        <div className="rounded-md border border-purple-200 bg-purple-50 p-3 space-y-2">
          <div className="flex items-center gap-4 text-sm">
            {newCount > 0 && (
              <span className="text-purple-700 font-medium">
                {newCount} new file{newCount !== 1 ? "s" : ""} to upload
              </span>
            )}
            {alreadyCount > 0 && (
              <span className="text-gray-500">
                {alreadyCount} already uploaded
              </span>
            )}
            {unmappedCount > 0 && (
              <span className="text-orange-600">
                {unmappedCount} unrecognized
              </span>
            )}
          </div>

          {newCount > 0 && (
            <div>
              <button
                type="button"
                onClick={() => setShowNewFiles(!showNewFiles)}
                className="text-xs text-purple-600 hover:text-purple-800"
              >
                {showNewFiles ? "Hide" : "Show"} new files
              </button>
              {showNewFiles && (
                <ul className="mt-1 max-h-40 overflow-y-auto text-xs text-gray-600 space-y-0.5">
                  {filterResult.new_files.map((f) => (
                    <li key={f} className="truncate">
                      {f}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {newCount === 0 && alreadyCount > 0 && (
            <p className="text-sm text-green-700">
              All matching files are already uploaded — nothing new to upload.
            </p>
          )}
        </div>
      )}

      {error && (
        <div className="rounded-md bg-red-50 border border-red-200 p-3 text-sm text-red-700">
          {error}
        </div>
      )}
    </div>
  );
}
