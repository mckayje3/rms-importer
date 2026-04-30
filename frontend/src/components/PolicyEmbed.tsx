"use client";

/**
 * Shared layout for legal pages (Privacy, Cookies, Terms).
 *
 * Iframes a hosted policy (iubenda) so the canonical URL stays on our
 * domain — customers and marketplace reviewers see the policy at e.g.
 * `<our-domain>/privacy`, not `iubenda.com/...`. Includes a fallback link
 * in case the iframe is blocked.
 */

interface PolicyEmbedProps {
  title: string;
  iframeUrl: string;
  fallbackUrl?: string;
}

export function PolicyEmbed({ title, iframeUrl, fallbackUrl }: PolicyEmbedProps) {
  const visitUrl = fallbackUrl || iframeUrl;
  return (
    <main className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-2xl font-bold text-gray-900">{title}</h1>
          <a
            href="/"
            className="text-sm text-orange-600 hover:text-orange-800"
          >
            ← Back to app
          </a>
        </div>
        <p className="text-sm text-gray-600 mb-4">
          If the policy doesn&apos;t load below, you can{" "}
          <a
            href={visitUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-orange-600 hover:text-orange-800 underline"
          >
            open it in a new tab
          </a>
          .
        </p>
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <iframe
            src={iframeUrl}
            title={title}
            className="w-full"
            style={{ minHeight: "70vh", border: 0 }}
          />
        </div>
      </div>
    </main>
  );
}
