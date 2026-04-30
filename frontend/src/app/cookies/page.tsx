import { PolicyEmbed } from "@/components/PolicyEmbed";

const DEFAULT_COOKIE_URL =
  "https://www.iubenda.com/privacy-policy/91796741/cookie-policy";

export const metadata = {
  title: "Cookie Policy — RMS Importer",
};

export default function CookiesPage() {
  const url = process.env.NEXT_PUBLIC_COOKIE_URL || DEFAULT_COOKIE_URL;
  return <PolicyEmbed title="Cookie Policy" iframeUrl={url} />;
}
