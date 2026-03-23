"use client";

import { useState, useMemo } from "react";
import type {
  MatchContractorsResponse,
  VendorMatchResult,
  ProcoreVendor,
} from "@/types";
import { rms } from "@/lib/api";

interface ContractorMatchReviewProps {
  sessionId: string;
  matchResults: MatchContractorsResponse;
  vendors: ProcoreVendor[];
  onConfirmAll: () => void;
  onBack: () => void;
}

type FilterStatus = "all" | "matched" | "unmatched" | "fuzzy";

export function ContractorMatchReview({
  sessionId,
  matchResults,
  vendors,
  onConfirmAll,
  onBack,
}: ContractorMatchReviewProps) {
  const [results, setResults] = useState(matchResults.results);
  const [filter, setFilter] = useState<FilterStatus>("all");
  const [updating, setUpdating] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  // Categorize results
  const categorized = useMemo(() => {
    const entries = Object.entries(results);
    return {
      exact: entries.filter(([, r]) => r.exact_match),
      fuzzy: entries.filter(([, r]) => r.vendor_id && !r.exact_match),
      unmatched: entries.filter(([, r]) => !r.vendor_id),
    };
  }, [results]);

  // Filter results
  const filteredResults = useMemo(() => {
    let entries = Object.entries(results);

    // Apply status filter
    if (filter === "matched") {
      entries = entries.filter(([, r]) => r.exact_match);
    } else if (filter === "fuzzy") {
      entries = entries.filter(([, r]) => r.vendor_id && !r.exact_match);
    } else if (filter === "unmatched") {
      entries = entries.filter(([, r]) => !r.vendor_id);
    }

    // Apply search filter
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      entries = entries.filter(
        ([section, r]) =>
          section.toLowerCase().includes(query) ||
          r.input_name.toLowerCase().includes(query) ||
          r.vendor_name?.toLowerCase().includes(query)
      );
    }

    return entries;
  }, [results, filter, searchQuery]);

  // Handle vendor selection change
  const handleVendorChange = async (section: string, vendorId: number) => {
    setUpdating(section);

    try {
      const response = await rms.confirmMatch(sessionId, section, vendorId);

      // Update local state
      setResults((prev) => ({
        ...prev,
        [section]: {
          ...prev[section],
          vendor_id: vendorId,
          vendor_name: response.vendor_name || vendors.find((v) => v.id === vendorId)?.name || null,
          match_score: 100,
          exact_match: true, // User confirmed = treat as exact
        },
      }));
    } catch (error) {
      console.error("Failed to confirm match:", error);
    } finally {
      setUpdating(null);
    }
  };

  // Get score badge color
  const getScoreBadge = (result: VendorMatchResult) => {
    if (!result.vendor_id) {
      return (
        <span className="px-2 py-1 text-xs font-medium rounded-full bg-red-100 text-red-700">
          No Match
        </span>
      );
    }
    if (result.exact_match) {
      return (
        <span className="px-2 py-1 text-xs font-medium rounded-full bg-green-100 text-green-700">
          Exact
        </span>
      );
    }
    if (result.match_score >= 80) {
      return (
        <span className="px-2 py-1 text-xs font-medium rounded-full bg-yellow-100 text-yellow-700">
          {result.match_score}%
        </span>
      );
    }
    return (
      <span className="px-2 py-1 text-xs font-medium rounded-full bg-orange-100 text-orange-700">
        {result.match_score}%
      </span>
    );
  };

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <div className="text-2xl font-bold text-gray-900">
            {matchResults.total_contractors}
          </div>
          <div className="text-sm text-gray-500">Total Contractors</div>
        </div>
        <div className="bg-white border border-green-200 rounded-lg p-4">
          <div className="text-2xl font-bold text-green-600">
            {categorized.exact.length}
          </div>
          <div className="text-sm text-gray-500">Exact Matches</div>
        </div>
        <div className="bg-white border border-yellow-200 rounded-lg p-4">
          <div className="text-2xl font-bold text-yellow-600">
            {categorized.fuzzy.length}
          </div>
          <div className="text-sm text-gray-500">Fuzzy Matches</div>
        </div>
        <div className="bg-white border border-red-200 rounded-lg p-4">
          <div className="text-2xl font-bold text-red-600">
            {categorized.unmatched.length}
          </div>
          <div className="text-sm text-gray-500">Unmatched</div>
        </div>
      </div>

      {/* Info Banner */}
      {categorized.unmatched.length > 0 && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <h3 className="text-sm font-medium text-yellow-800 mb-1">
            Action Required
          </h3>
          <p className="text-sm text-yellow-700">
            {categorized.unmatched.length} contractor(s) could not be matched to your
            Procore Directory. Select a vendor from the dropdown or add them to
            your Directory first.
          </p>
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-4">
        <div className="flex gap-2">
          <button
            onClick={() => setFilter("all")}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
              filter === "all"
                ? "bg-gray-900 text-white"
                : "bg-gray-100 text-gray-700 hover:bg-gray-200"
            }`}
          >
            All ({Object.keys(results).length})
          </button>
          <button
            onClick={() => setFilter("matched")}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
              filter === "matched"
                ? "bg-green-600 text-white"
                : "bg-green-50 text-green-700 hover:bg-green-100"
            }`}
          >
            Exact ({categorized.exact.length})
          </button>
          <button
            onClick={() => setFilter("fuzzy")}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
              filter === "fuzzy"
                ? "bg-yellow-600 text-white"
                : "bg-yellow-50 text-yellow-700 hover:bg-yellow-100"
            }`}
          >
            Fuzzy ({categorized.fuzzy.length})
          </button>
          <button
            onClick={() => setFilter("unmatched")}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
              filter === "unmatched"
                ? "bg-red-600 text-white"
                : "bg-red-50 text-red-700 hover:bg-red-100"
            }`}
          >
            Unmatched ({categorized.unmatched.length})
          </button>
        </div>

        <div className="flex-1">
          <input
            type="text"
            placeholder="Search sections or contractors..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-orange-500 focus:border-orange-500"
          />
        </div>
      </div>

      {/* Results Table */}
      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Spec Section
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Contractor (from mapping)
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Procore Vendor
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-24">
                Status
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {filteredResults.map(([section, result]) => (
              <tr
                key={section}
                className={`${
                  updating === section ? "opacity-50" : ""
                } hover:bg-gray-50`}
              >
                <td className="px-4 py-3 text-sm font-mono text-gray-900">
                  {section}
                </td>
                <td className="px-4 py-3 text-sm text-gray-700">
                  {result.input_name}
                </td>
                <td className="px-4 py-3">
                  <select
                    value={result.vendor_id || ""}
                    onChange={(e) =>
                      handleVendorChange(section, parseInt(e.target.value))
                    }
                    disabled={updating === section}
                    className={`w-full px-2 py-1 text-sm border rounded-md focus:ring-2 focus:ring-orange-500 ${
                      !result.vendor_id
                        ? "border-red-300 bg-red-50"
                        : result.exact_match
                        ? "border-green-300 bg-green-50"
                        : "border-yellow-300 bg-yellow-50"
                    }`}
                  >
                    <option value="">-- Select Vendor --</option>
                    {/* Show suggestions first */}
                    {result.suggestions.length > 0 && (
                      <optgroup label="Suggestions">
                        {result.suggestions.map((s) => (
                          <option key={s.vendor_id} value={s.vendor_id}>
                            {s.vendor_name} ({s.score}%)
                          </option>
                        ))}
                      </optgroup>
                    )}
                    {/* Then all vendors */}
                    <optgroup label="All Vendors">
                      {vendors
                        .filter((v) => v.is_active)
                        .sort((a, b) => a.name.localeCompare(b.name))
                        .map((v) => (
                          <option key={v.id} value={v.id}>
                            {v.name}
                          </option>
                        ))}
                    </optgroup>
                  </select>
                </td>
                <td className="px-4 py-3">{getScoreBadge(result)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {filteredResults.length === 0 && (
          <div className="px-4 py-8 text-center text-gray-500">
            No contractors match your filter.
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between pt-4">
        <button
          onClick={onBack}
          className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
        >
          Back
        </button>

        <div className="flex items-center gap-3">
          {categorized.unmatched.length > 0 && (
            <span className="text-sm text-gray-500">
              {categorized.unmatched.length} unmatched - import will skip these
            </span>
          )}
          <button
            onClick={onConfirmAll}
            className="px-6 py-2 text-sm font-medium text-white bg-orange-500 rounded-md hover:bg-orange-600 transition-colors"
          >
            Continue with Import
          </button>
        </div>
      </div>
    </div>
  );
}
