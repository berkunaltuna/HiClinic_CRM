/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Allow running inside docker-compose on 0.0.0.0
  output: 'standalone'
};

module.exports = nextConfig;
