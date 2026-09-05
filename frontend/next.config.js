/** @type {import('next').NextConfig} */
// BACKEND_URL: the FastAPI origin this server proxies /api and /auth to.
// Defaults to localhost:8000 for local dev; set to the Railway backend's
// public URL in Vercel's project environment variables.
const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';

const nextConfig = {
  agentRules: false,
  async rewrites() {
    return [
      { source: '/api/:path*', destination: `${backendUrl}/api/:path*` },
      { source: '/auth/:path*', destination: `${backendUrl}/auth/:path*` },
    ];
  },
};
module.exports = nextConfig;
