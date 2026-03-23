"use client";

import { useState, useEffect } from "react";
import type { ProcoreCompany, ProcoreProject, ProcoreStats } from "@/types";
import { projects } from "@/lib/api";

interface ProjectSelectorProps {
  onProjectSelect: (
    company: ProcoreCompany,
    project: ProcoreProject,
    stats: ProcoreStats
  ) => void;
}

export function ProjectSelector({ onProjectSelect }: ProjectSelectorProps) {
  const [companies, setCompanies] = useState<ProcoreCompany[]>([]);
  const [projectList, setProjectList] = useState<ProcoreProject[]>([]);
  const [selectedCompany, setSelectedCompany] = useState<ProcoreCompany | null>(null);
  const [selectedProject, setSelectedProject] = useState<ProcoreProject | null>(null);
  const [stats, setStats] = useState<ProcoreStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingStats, setLoadingStats] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load companies on mount
  useEffect(() => {
    async function loadCompanies() {
      try {
        const data = await projects.getCompanies();
        setCompanies(data);
        if (data.length === 1) {
          setSelectedCompany(data[0]);
        }
      } catch (err) {
        setError("Failed to load companies");
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    loadCompanies();
  }, []);

  // Load projects when company changes
  useEffect(() => {
    if (!selectedCompany) {
      setProjectList([]);
      return;
    }

    async function loadProjects() {
      setLoading(true);
      try {
        const data = await projects.getProjects(selectedCompany!.id);
        setProjectList(data);
        setSelectedProject(null);
        setStats(null);
      } catch (err) {
        setError("Failed to load projects");
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    loadProjects();
  }, [selectedCompany]);

  // Load stats when project changes
  useEffect(() => {
    if (!selectedProject) {
      setStats(null);
      return;
    }

    async function loadStats() {
      setLoadingStats(true);
      try {
        const data = await projects.getStats(selectedProject!.id, selectedCompany!.id);
        setStats(data);
      } catch (err) {
        console.error("Failed to load stats:", err);
      } finally {
        setLoadingStats(false);
      }
    }
    loadStats();
  }, [selectedProject]);

  const handleContinue = () => {
    if (selectedCompany && selectedProject && stats) {
      onProjectSelect(selectedCompany, selectedProject, stats);
    }
  };

  if (loading && companies.length === 0) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 text-red-700 p-4 rounded-lg">
        {error}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Company Select */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Company
        </label>
        <select
          value={selectedCompany?.id || ""}
          onChange={(e) => {
            const company = companies.find((c) => c.id === Number(e.target.value));
            setSelectedCompany(company || null);
          }}
          className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-orange-500 focus:border-orange-500"
        >
          <option value="">Select a company...</option>
          {companies.map((company) => (
            <option key={company.id} value={company.id}>
              {company.name}
            </option>
          ))}
        </select>
      </div>

      {/* Project Select */}
      {selectedCompany && (
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Project
          </label>
          {loading ? (
            <div className="flex items-center gap-2 px-4 py-2 text-sm text-gray-500">
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-orange-500"></div>
              Loading projects...
            </div>
          ) : (
            <select
              value={selectedProject?.id || ""}
              onChange={(e) => {
                const project = projectList.find((p) => p.id === Number(e.target.value));
                setSelectedProject(project || null);
              }}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-orange-500 focus:border-orange-500"
            >
              <option value="">Select a project...</option>
              {projectList.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          )}
        </div>
      )}

      {/* Loading Stats */}
      {loadingStats && (
        <div className="bg-orange-50 border border-orange-200 rounded-lg p-4">
          <div className="flex items-center gap-3">
            <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-orange-500"></div>
            <div>
              <p className="text-sm font-medium text-orange-800">Loading project data...</p>
              <p className="text-xs text-orange-600">This may take up to a minute for large projects.</p>
            </div>
          </div>
        </div>
      )}

      {/* Project Stats */}
      {stats && (
        <div className="bg-gray-50 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-700 mb-3">
            Current Procore Data
          </h3>
          <div className="grid grid-cols-3 gap-4 text-center">
            <div>
              <p className="text-2xl font-bold text-gray-900">{stats.submittal_count}</p>
              <p className="text-xs text-gray-500">Submittals</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-gray-900">{stats.spec_section_count}</p>
              <p className="text-xs text-gray-500">Spec Sections</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-gray-900">{stats.revision_count}</p>
              <p className="text-xs text-gray-500">Revisions</p>
            </div>
          </div>
        </div>
      )}

      {/* Continue Button */}
      <button
        onClick={handleContinue}
        disabled={!selectedCompany || !selectedProject || !stats}
        className={`
          w-full py-3 px-4 rounded-lg font-medium transition-colors
          ${
            selectedCompany && selectedProject && stats
              ? "bg-orange-500 text-white hover:bg-orange-600"
              : "bg-gray-200 text-gray-500 cursor-not-allowed"
          }
        `}
      >
        Continue
      </button>
    </div>
  );
}
