"use client";

/**
 * Small site-wide footer that surfaces a support contact and a link to the
 * user guide. Procore Marketplace expects every embedded app to have a
 * reachable support contact from inside the app itself.
 *
 * Configurable via env vars (set on Vercel for the deployed build):
 *   NEXT_PUBLIC_SUPPORT_EMAIL — defaults to a placeholder
 *   NEXT_PUBLIC_HELP_URL     — defaults to the GitHub README
 */

const SUPPORT_EMAIL =
  process.env.NEXT_PUBLIC_SUPPORT_EMAIL || "support@example.com";
const HELP_URL =
  process.env.NEXT_PUBLIC_HELP_URL ||
  "https://github.com/mckayje3/rms-importer#readme";

interface HelpFooterProps {
  /** Hide the footer on screens where it would be visually noisy (e.g. auth). */
  hidden?: boolean;
}

export function HelpFooter({ hidden = false }: HelpFooterProps) {
  if (hidden) return null;

  return (
    <footer className="max-w-2xl mx-auto px-6 pb-6 pt-2">
      <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-xs text-gray-500">
        <a
          href={HELP_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="hover:text-gray-700 hover:underline"
        >
          User Guide
        </a>
        <span className="text-gray-300">·</span>
        <a href="/privacy" className="hover:text-gray-700 hover:underline">
          Privacy
        </a>
        <span className="text-gray-300">·</span>
        <a href="/cookies" className="hover:text-gray-700 hover:underline">
          Cookies
        </a>
        <span className="text-gray-300">·</span>
        <a
          href={`mailto:${SUPPORT_EMAIL}?subject=RMS%20Importer%20support`}
          className="hover:text-gray-700 hover:underline"
        >
          Need help? {SUPPORT_EMAIL}
        </a>
      </div>
    </footer>
  );
}
