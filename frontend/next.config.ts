import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          // Allow Procore to embed this app in an iframe
          {
            key: "Content-Security-Policy",
            value: "frame-ancestors 'self' https://*.procore.com",
          },
          // Remove X-Frame-Options so CSP frame-ancestors takes precedence
          {
            key: "X-Frame-Options",
            value: "ALLOWALL",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
