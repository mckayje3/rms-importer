"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { rfi as rfiApi } from "@/lib/api";
import type { RFIJobStatus } from "@/types";

interface RFIFileUploadProps {
  projectId: number;
  companyId: number;
  excludeFiles?: string[];
}

interface FilterResult {
  new_files: string[];
  already_attached: string[];
  unmapped_files: string[];
  total_checked: number;
}

export function RFIFileUpload({ projectId, companyId, excludeFiles = [] }: RFIFileUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [allFiles, setAllFiles] = useState<File[]>([]);
  const [filterResult, setFilterResult] = useState<FilterResult | null>(null);
  const [isFiltering, setIsFiltering] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<RFIJobStatus | null>(null);
  const [error, setError] = useState("");
  const [showNewFiles, setShowNewFiles] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Poll job status
  useEffect(() => {
    if (!jobId) return;

    const poll = async () => {
      try {
        const status = await rfiApi.getJobStatus(jobId);
        setJobStatus(status);
        if (status.status === "completed" || status.status === "failed") {
          if (pollRef.current) clearInterval(pollRef.current);
          setIsUploading(false);
        }
      } catch {
        // Ignore poll errors
      }
    };

    poll();
    pollRef.current = setInterval(poll, 5000);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [jobId]);

  const handleFolderSelect = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || []);
      if (files.length === 0) return;

      // Filter to RFI-prefixed files, excluding response files already handled
      const excludeSet = new Set(excludeFiles);
      const rfiFiles = files
        .filter((f) => /^RFI-\d+/i.test(f.name))
        .filter((f) => !excludeSet.has(f.name));

      setAllFiles(rfiFiles);
      setFilterResult(null);
      setError("");
      setJobId(null);
      setJobStatus(null);

      if (rfiFiles.length === 0) {
        setError(
          `Found ${files.length} files but none match the "RFI-XXXX" naming convention.`
        );
        return;
      }

      // Send filenames to backend for filtering (uses cached data, no API calls)
      setIsFiltering(true);
      try {
        const filenames = rfiFiles.map((f) => f.name);
        const result = await rfiApi.filterFiles(projectId, filenames);
        setFilterResult(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to check files");
      } finally {
        setIsFiltering(false);
      }
    },
    [projectId]
  );

  const handleUpload = useCallback(async () => {
    if (!filterResult || filterResult.new_files.length === 0) return;

    // Only upload new files
    const newFileNames = new Set(filterResult.new_files);
    const filesToUpload = allFiles.filter((f) => newFileNames.has(f.name));

    setIsUploading(true);
    setError("");

    try {
      const result = await rfiApi.uploadFiles(
        projectId,
        filesToUpload,
        companyId,
        (batch, total) => {
          setUploadProgress(`Sending batch ${batch} of ${total}...`);
        }
      );

      if (result.job_id) {
        setJobId(result.job_id);
        setUploadProgress("");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
      setIsUploading(false);
    }
  }, [filterResult, allFiles, projectId, companyId]);

  const handleClear = useCallback(() => {
    setAllFiles([]);
    setFilterResult(null);
    setError("");
    setUploadProgress("");
    setIsUploading(false);
    setJobId(null);
    setJobStatus(null);
    if (inputRef.current) {
      inputRef.current.value = "";
    }
  }, []);

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium text-gray-700">RFI File Attachments</h3>
      <p className="text-xs text-gray-500">
        Select the RMS Files folder containing RFI attachments. Files are matched
        by &quot;RFI-XXXX&quot; prefix and attached to the corresponding RFI in Procore.
      </p>

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
          id="rfi-folder-upload"
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

        {allFiles.length > 0 && !isUploading && !jobId && (
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
      {filterResult && !jobId && (
        <div className="rounded-md border border-purple-200 bg-purple-50 p-3 space-y-2">
          <div className="flex items-center gap-4 text-sm">
            {filterResult.new_files.length > 0 && (
              <span className="text-purple-700 font-medium">
                {filterResult.new_files.length} new file{filterResult.new_files.length !== 1 ? "s" : ""} to upload
              </span>
            )}
            {filterResult.already_attached.length > 0 && (
              <span className="text-gray-500">
                {filterResult.already_attached.length} already attached
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
                    <li key={f} className="truncate">{f}</li>
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
              All files are already attached. Nothing new to upload.
            </p>
          )}
        </div>
      )}

      {/* Upload progress */}
      {isUploading && !jobId && uploadProgress && (
        <div className="flex items-center gap-2 text-sm text-purple-600">
          <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          {uploadProgress}
        </div>
      )}

      {/* Job status */}
      {jobStatus && (
        <div className="rounded-md border border-purple-200 bg-purple-50 p-3 space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-purple-700 font-medium">
              {jobStatus.status === "completed" || jobStatus.status === "failed"
                ? `${jobStatus.created} file${jobStatus.created !== 1 ? "s" : ""} attached`
                : `Attaching files... ${jobStatus.created} / ${jobStatus.total}`}
            </span>
            <span className={`text-xs font-medium ${
              jobStatus.status === "completed" ? "text-green-600"
                : jobStatus.status === "failed" ? "text-red-600"
                : "text-blue-600"
            }`}>
              {jobStatus.status}
            </span>
          </div>

          {(jobStatus.status === "running" || jobStatus.status === "queued") && (
            <div className="w-full bg-gray-200 rounded-full h-1.5">
              <div
                className="bg-purple-500 h-1.5 rounded-full transition-all duration-500"
                style={{
                  width: `${jobStatus.total > 0
                    ? Math.round((jobStatus.created / jobStatus.total) * 100)
                    : 0}%`,
                }}
              />
            </div>
          )}

          {jobStatus.errors.length > 0 && (
            <div className="text-xs text-red-600 mt-1">
              {jobStatus.errors.slice(0, 3).map((e, i) => <p key={i}>{e}</p>)}
              {jobStatus.errors.length > 3 && (
                <p>...and {jobStatus.errors.length - 3} more</p>
              )}
            </div>
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
