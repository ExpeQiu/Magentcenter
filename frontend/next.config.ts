import type { NextConfig } from "next";

const API_PORT = process.env.API_PORT || "8013";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `http://127.0.0.1:${API_PORT}/api/:path*`,
      },
      {
        source: "/ws/:path*",
        destination: `http://127.0.0.1:${API_PORT}/ws/:path*`,
      },
    ];
  },
};

export default nextConfig;
