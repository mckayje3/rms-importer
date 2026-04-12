"use client";

import type { ToolType } from "@/types";

interface ToolOption {
  id: ToolType;
  title: string;
  description: string;
  icon: React.ReactNode;
}

const TOOLS: ToolOption[] = [
  {
    id: "submittals",
    title: "Submittals",
    description: "Import and sync submittal register data from RMS to Procore.",
    icon: (
      <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
          d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    ),
  },
  {
    id: "rfis",
    title: "RFIs",
    description: "Import Requests for Information from RMS into Procore.",
    icon: (
      <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
          d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
];

interface ToolSelectorProps {
  onSelect: (tool: ToolType) => void;
}

export function ToolSelector({ onSelect }: ToolSelectorProps) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      {TOOLS.map((tool) => (
        <button
          key={tool.id}
          onClick={() => onSelect(tool.id)}
          className="flex flex-col items-center p-6 bg-white border-2 border-gray-200 rounded-xl hover:border-orange-400 hover:shadow-md transition-all text-center group"
        >
          <div className="w-14 h-14 rounded-full bg-orange-50 flex items-center justify-center text-orange-500 mb-3 group-hover:bg-orange-100 transition-colors">
            {tool.icon}
          </div>
          <h3 className="text-lg font-semibold text-gray-900 mb-1">{tool.title}</h3>
          <p className="text-sm text-gray-500">{tool.description}</p>
        </button>
      ))}
    </div>
  );
}
