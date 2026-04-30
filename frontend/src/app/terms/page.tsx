import fs from "fs";
import path from "path";

export const metadata = {
  title: "Terms of Service — RMS Importer",
};

/**
 * Terms of Service page.
 *
 * The HTML in `./content.html` is the Termly-generated free-tier output;
 * its license requires us to leave their attribution intact (the credit
 * line at the bottom is part of the file). The Server Component reads the
 * file at request/build time and injects it into the page via
 * dangerouslySetInnerHTML.
 *
 * If you upgrade to Termly PRO+ (or migrate to Common Paper) and want a
 * hosted iframe instead, replace this page with the same pattern as
 * `app/privacy/page.tsx`, pointing `NEXT_PUBLIC_TERMS_URL` at the new
 * source.
 */
export default function TermsPage() {
  const html = fs.readFileSync(
    path.join(process.cwd(), "src/app/terms/content.html"),
    "utf-8"
  );

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-2xl font-bold text-gray-900">Terms of Service</h1>
          <a
            href="/"
            className="text-sm text-orange-600 hover:text-orange-800"
          >
            ← Back to app
          </a>
        </div>
        <div
          className="bg-white rounded-lg border border-gray-200 p-6"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      </div>
    </main>
  );
}
