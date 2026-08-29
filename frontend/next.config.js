/** @type {import('next').NextConfig} */
const nextConfig = {
  agentRules: false,
  async rewrites() {
    return [
      { source: '/api/:path*', destination: 'http://localhost:8000/api/:path*' },
      { source: '/auth/:path*', destination: 'http://localhost:8000/auth/:path*' },
    ];
  },
};
module.exports = nextConfig;
