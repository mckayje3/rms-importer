"use client";

import { useState } from "react";
import type { ObservationSyncPlan, ObservationType } from "@/types";

/**
 * Post-import detail panel for the QAQC Observations module.
 *
 * The plan only carries aggregate counts for observations (no per-record
 * detail), so this is lighter than the Submittals/RFI versions. The
 * value-add over the existing static summary is showing the actual
 * names of locations that were created and confirming the chosen
 * observation type, alongside the success counts.
 */

interface ObservationImportResult {
  observations_created: number;
  locations_created: number;
  errors: string[];
}

interface ObservationsResultSummaryProps {
  plan: ObservationSyncPlan;
  result: ObservationImportResult;
  /** ID of the observation type selected on Review (for label lookup). */
  selectedTypeId?: number | null;
}

function CheckIcon() {
  return (
    <svg
      className="w-4 h-4 text-green-600 flex-shrink-0"
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2.5}
        d="M5 13l4 4L19 7"
      />
    </svg>
  );
}

function Caret({ open }: { open: boolean }) {
  return (
    <svg
      className={`w-5 h-5 text-gray-500 transition-transform ${open ? "rotate-180" : ""}`}
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
    </svg>
  );
}

export function ObservationsResultSummary({
  plan,
  result,
  selectedTypeId,
}: ObservationsResultSummaryProps) {
  const [openSection, setOpenSection] = useState<string | null>("locations");

  const showObservations = result.observations_created > 0;
  const showLocations =
    result.locations_created > 0 && plan.locations_to_create.length > 0;
  const errorCount = result.errors.length;

  const anything = showObservations || showLocations;
  if (!anything) return null;

  const selectedType: ObservationType | undefined = plan.observation_types.find(
    (t) => t.id === selectedTypeId
  );

  const toggle = (key: string) =>
    setOpenSection((current) => (current === key ? null : key));

  return (
    <div className="text-left max-w-2xl mx-auto mb-6 space-y-3">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-base font-semibold text-gray-900">Changes Applied</h3>
        {errorCount > 0 && (
          <span className="text-xs text-red-600">
            {errorCount} error{errorCount !== 1 ? "s" : ""} — see below
          </span>
        )}
      </div>

      {/* Observations created */}
      {showObservations && (
        <div className="border rounded-lg overflow-hidden">
          <div className="flex items-center justify-between p-3 bg-blue-50">
            <div className="flex items-center gap-3">
              <CheckIcon />
              <span className="font-medium text-blue-800">
                {result.observations_created} Observation{result.observations_created !== 1 ? "s" : ""} Created
                {selectedType && (
                  <span className="text-sm font-normal text-blue-700">
                    {" "}as &ldquo;{selectedType.name}&rdquo;
                  </span>
                )}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Locations created */}
      {showLocations && (
        <div className="border rounded-lg overflow-hidden">
          <button
            onClick={() => toggle("locations")}
            className="w-full flex items-center justify-between p-3 bg-green-50 hover:bg-green-100 transition-colors"
          >
            <div className="flex items-center gap-3">
              <CheckIcon />
              <span className="font-medium text-green-800">
                {result.locations_created} Location{result.locations_created !== 1 ? "s" : ""} Created
              </span>
            </div>
            <Caret open={openSection === "locations"} />
          </button>
          {openSection === "locations" && (
            <div className="p-4 border-t border-green-200 max-h-64 overflow-y-auto">
              <ul className="text-sm text-gray-700 space-y-1">
                {plan.locations_to_create.map((loc) => (
                  <li key={loc} className="font-mono">
                    {loc}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
