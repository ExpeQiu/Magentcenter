/** @type {import('next').NextConfig} */
const API_PORT = process.env.API_PORT || "8013";

const nextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `http://localhost:${API_PORT}/api/:path*`,
      },
      {
        source: "/ws/:path*",
        destination: `http://localhost:${API_PORT}/ws/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
