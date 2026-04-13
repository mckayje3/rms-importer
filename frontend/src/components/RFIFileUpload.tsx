"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { rfi as rfiApi } from "@/lib/api";
import type { RFIJobStatus } from "@/types";

interface RFIFileUploadProps {
  projectId: number;
  companyId: number;
}

export function RFIFileUpload({ projectId, companyId }: RFIFileUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [allFiles, setAllFiles] = useState<File[]>([]);
  const [rfiFiles, setRfiFiles] = useState<File[]>([]);
  const [nonRfiCount, setNonRfiCount] = useState(0);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<RFIJobStatus | null>(null);
  const [error, setError] = useState("");
  const [showFiles, setShowFiles] = useState(false);
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
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || []);
      if (files.length === 0) return;

      // Filter to RFI-prefixed files
      const rfi = files.filter((f) => /^RFI-\d+/i.test(f.name));
      const nonRfi = files.length - rfi.length;

      setAllFiles(files);
      setRfiFiles(rfi);
      setNonRfiCount(nonRfi);
      setError("");
      setJobId(null);
      setJobStatus(null);

      if (rfi.length === 0) {
        setError(
          `Found ${files.length} files but none match the "RFI-XXXX" naming convention.`
        );
      }
    },
    []
  );

  const handleUpload = useCallback(async () => {
    if (rfiFiles.length === 0) return;

    setIsUploading(true);
    setError("");

    try {
      const result = await rfiApi.uploadFiles(
        projectId,
        rfiFiles,
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
  }, [rfiFiles, projectId, companyId]);

  const handleClear = useCallback(() => {
    setAllFiles([]);
    setRfiFiles([]);
    setNonRfiCount(0);
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
          disabled={isUploading}
          className="px-4 py-2 text-sm font-medium text-white bg-purple-600 rounded-md
            hover:bg-purple-700 disabled:bg-gray-400 disabled:cursor-not-allowed
            transition-colors"
        >
          Select RMS Files Folder
        </button>

        {rfiFiles.length > 0 && !isUploading && !jobId && (
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
      {rfiFiles.length > 0 && !jobId && (
        <div className="rounded-md border border-purple-200 bg-purple-50 p-3 space-y-2">
          <div className="flex items-center gap-4 text-sm">
            <span className="text-purple-700 font-medium">
              {rfiFiles.length} RFI file{rfiFiles.length !== 1 ? "s" : ""} found
            </span>
            {nonRfiCount > 0 && (
              <span className="text-gray-500">
                {nonRfiCount} non-RFI file{nonRfiCount !== 1 ? "s" : ""} skipped
              </span>
            )}
          </div>

          <div>
            <button
              type="button"
              onClick={() => setShowFiles(!showFiles)}
              className="text-xs text-purple-600 hover:text-purple-800"
            >
              {showFiles ? "Hide" : "Show"} files
            </button>
            {showFiles && (
              <ul className="mt-1 max-h-40 overflow-y-auto text-xs text-gray-600 space-y-0.5">
                {rfiFiles.map((f) => (
                  <li key={f.name} className="truncate">{f.name}</li>
                ))}
              </ul>
            )}
          </div>

          {!isUploading && (
            <button
              type="button"
              onClick={handleUpload}
              className="mt-2 px-4 py-2 text-sm font-medium text-white bg-purple-600
                rounded-md hover:bg-purple-700 transition-colors"
            >
              Upload & Attach {rfiFiles.length} File{rfiFiles.length !== 1 ? "s" : ""}
            </button>
          )}
        </div>
      )}

      {/* Upload / job progress */}
      {isUploading && !jobId && uploadProgress && (
        <div className="flex items-center gap-2 text-sm text-purple-600">
          <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          {uploadProgress}
        </div>
      )}

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
