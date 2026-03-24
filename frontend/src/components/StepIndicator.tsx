"use client";

import type { AppStep } from "@/types";

const STEPS: { key: AppStep; label: string }[] = [
  { key: "auth", label: "Connect" },
  { key: "select-project", label: "Select Project" },
  { key: "upload-rms", label: "Upload RMS" },
  { key: "analyze", label: "Analyze" },
  { key: "review", label: "Review" },
  { key: "import", label: "Import" },
];

interface StepIndicatorProps {
  currentStep: AppStep;
  isEmbedded?: boolean;
}

export function StepIndicator({ currentStep, isEmbedded = false }: StepIndicatorProps) {
  // sync-review maps to the same position as review in the step bar
  const effectiveStep = currentStep === "sync-review" ? "review" : currentStep;
  // When embedded, skip "Connect" and "Select Project" steps (handled automatically)
  const visibleSteps = isEmbedded
    ? STEPS.filter(s => s.key !== "auth" && s.key !== "select-project")
    : STEPS;
  const currentIndex = visibleSteps.findIndex((s) => s.key === effectiveStep);

  return (
    <div className="w-full py-4">
      <div className="flex items-center justify-center gap-2">
        {visibleSteps.map((step, index) => {
          const isActive = index === currentIndex;
          const isCompleted = index < currentIndex;
          const isPending = index > currentIndex;

          return (
            <div key={step.key} className="flex items-center">
              <div className="flex flex-col items-center">
                <div
                  className={`
                    w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium
                    ${isCompleted ? "bg-green-500 text-white" : ""}
                    ${isActive ? "bg-orange-500 text-white" : ""}
                    ${isPending ? "bg-gray-200 text-gray-500" : ""}
                  `}
                >
                  {isCompleted ? (
                    <svg
                      className="w-4 h-4"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M5 13l4 4L19 7"
                      />
                    </svg>
                  ) : (
                    index + 1
                  )}
                </div>
                <span
                  className={`
                    mt-1 text-xs font-medium
                    ${isActive ? "text-orange-600" : ""}
                    ${isCompleted ? "text-green-600" : ""}
                    ${isPending ? "text-gray-400" : ""}
                  `}
                >
                  {step.label}
                </span>
              </div>
              {index < visibleSteps.length - 1 && (
                <div
                  className={`
                    w-12 h-0.5 mx-2 mt-[-16px]
                    ${index < currentIndex ? "bg-green-500" : "bg-gray-200"}
                  `}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
