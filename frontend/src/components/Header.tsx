"use client";

interface HeaderProps {
  isAuthenticated: boolean;
  onLogout?: () => void;
}

export function Header({ isAuthenticated, onLogout }: HeaderProps) {
  return (
    <header className="bg-white border-b border-gray-200 px-6 py-4">
      <div className="max-w-7xl mx-auto flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-orange-500 rounded-lg flex items-center justify-center">
            <span className="text-white font-bold text-lg">R</span>
          </div>
          <div>
            <h1 className="text-xl font-semibold text-gray-900">
              RMS Importer
            </h1>
            <p className="text-sm text-gray-500">
              Import submittal data from RMS to Procore
            </p>
          </div>
        </div>

        {isAuthenticated && onLogout && (
          <button
            onClick={onLogout}
            className="text-sm text-gray-600 hover:text-gray-900 px-4 py-2 rounded-md hover:bg-gray-100 transition-colors"
          >
            Sign Out
          </button>
        )}
      </div>
    </header>
  );
}
