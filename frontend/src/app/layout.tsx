import type { Metadata } from "next";
import Script from "next/script";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// iubenda Privacy Controls + Cookie Solution. Loaded site-wide so the cookie
// banner, consent management, and styled iubenda links all work everywhere.
// Override per environment via NEXT_PUBLIC_IUBENDA_WIDGET_URL on Vercel.
const IUBENDA_WIDGET_URL =
  process.env.NEXT_PUBLIC_IUBENDA_WIDGET_URL ||
  "https://embeds.iubenda.com/widgets/f1d823df-91c8-4f90-b102-91a0e8445a02.js";

export const metadata: Metadata = {
  title: "RMS Importer",
  description: "Import submittal data from USACE RMS to Procore",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <Script
          src={IUBENDA_WIDGET_URL}
          strategy="beforeInteractive"
          id="iubenda-widget"
        />
      </head>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-gray-50 min-h-screen`}
      >
        {children}
      </body>
    </html>
  );
}
