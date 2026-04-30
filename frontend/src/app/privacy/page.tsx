import { PolicyEmbed } from "@/components/PolicyEmbed";

const DEFAULT_PRIVACY_URL = "https://www.iubenda.com/privacy-policy/91796741";

export const metadata = {
  title: "Privacy Policy — RMS Importer",
};

export default function PrivacyPage() {
  const url = process.env.NEXT_PUBLIC_PRIVACY_URL || DEFAULT_PRIVACY_URL;
  return <PolicyEmbed title="Privacy Policy" iframeUrl={url} />;
}
