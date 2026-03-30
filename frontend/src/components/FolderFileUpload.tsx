"use client";

import { useState, useRef, useCallback } from "react";
import { sync } from "@/lib/api";
import type { FileFilterResponse } from "@/types";

interface FolderFileUploadProps {
  projectId: number;
  rmsSessionId: string;
  companyId: number;
  onUploadStarted: (jobId: string) => void;
}

export function FolderFileUpload({
  projectId,
  rmsSessionId,
  companyId,
  onUploadStarted,
}: FolderFileUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [allFiles, setAllFiles] = useState<File[]>([]);
  const [filterResult, setFilterResult] = useState<FileFilterResponse | null>(null);
  const [isFiltering, setIsFiltering] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [showNewFiles, setShowNewFiles] = useState(false);

  const handleFolderSelect = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || []);
      if (files.length === 0) return;

      // Filter to only Transmittal files (the ones that match our naming convention)
      const transmittalFiles = files.filter((f) =>
        f.name.startsWith("Transmittal ")
      );

      setAllFiles(transmittalFiles);
      setFilterResult(null);
      setError("");

      if (transmittalFiles.length === 0) {
        setError(
          `Found ${files.length} files but none match the "Transmittal ..." naming convention.`
        );
        return;
      }

      // Send filenames to backend for filtering
      setIsFiltering(true);
      try {
        const filenames = transmittalFiles.map((f) => f.name);
        const result = await sync.filterFiles(projectId, rmsSessionId, filenames);
        setFilterResult(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to check files");
      } finally {
        setIsFiltering(false);
      }
    },
    [projectId, rmsSessionId]
  );

  const handleUpload = useCallback(async () => {
    if (!filterResult || filterResult.new_files.length === 0) return;

    // Get only the new files from the full file list
    const newFileNames = new Set(filterResult.new_files);
    const filesToUpload = allFiles.filter((f) => newFileNames.has(f.name));

    setIsUploading(true);
    setError("");

    try {
      const result = await sync.uploadFiles(
        projectId,
        filesToUpload,
        rmsSessionId,
        companyId,
        undefined,
        (batch, total) => {
          setUploadProgress(`Sending batch ${batch} of ${total}...`);
        }
      );

      if (result.job_id) {
        onUploadStarted(result.job_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
      setIsUploading(false);
    }
  }, [filterResult, allFiles, projectId, rmsSessionId, companyId, onUploadStarted]);

  const handleClear = useCallback(() => {
    setAllFiles([]);
    setFilterResult(null);
    setError("");
    setUploadProgress("");
    setIsUploading(false);
    if (inputRef.current) {
      inputRef.current.value = "";
    }
  }, []);

  return (
    <div className="space-y-3">
      {/* Folder selection */}
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
          id="folder-upload"
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={isFiltering || isUploading}
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
          ) : (
            "Select RMS Files Folder"
          )}
        </button>

        {allFiles.length > 0 && !isUploading && (
          <button
            type="button"
            onClick={handleClear}
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            Clear
          </button>
        )}
      </div>

      {/* Filter results */}
      {filterResult && (
        <div className="rounded-md border border-purple-200 bg-purple-50 p-3 space-y-2">
          <div className="flex items-center gap-4 text-sm">
            {filterResult.new_files.length > 0 && (
              <span className="text-purple-700 font-medium">
                {filterResult.new_files.length} new file{filterResult.new_files.length !== 1 ? "s" : ""} to upload
              </span>
            )}
            {filterResult.already_uploaded.length > 0 && (
              <span className="text-gray-500">
                {filterResult.already_uploaded.length} already uploaded
              </span>
            )}
            {filterResult.unmapped_files.length > 0 && (
              <span className="text-orange-600">
                {filterResult.unmapped_files.length} unrecognized
              </span>
            )}
          </div>

          {/* Expandable list of new files */}
          {filterResult.new_files.length > 0 && (
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

          {/* Upload button */}
          {filterResult.new_files.length > 0 && !isUploading && (
            <button
              type="button"
              onClick={handleUpload}
              className="mt-2 px-4 py-2 text-sm font-medium text-white bg-purple-600
                rounded-md hover:bg-purple-700 transition-colors"
            >
              Upload & Attach {filterResult.new_files.length} File{filterResult.new_files.length !== 1 ? "s" : ""}
            </button>
          )}

          {filterResult.new_files.length === 0 && (
            <p className="text-sm text-green-700">
              All files are already uploaded. Nothing new to upload.
            </p>
          )}
        </div>
      )}

      {/* Upload progress */}
      {isUploading && uploadProgress && (
        <div className="flex items-center gap-2 text-sm text-purple-600">
          <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          {uploadProgress}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-md bg-red-50 border border-red-200 p-3 text-sm text-red-700">
          {error}
        </div>
      )}
    </div>
  );
}
