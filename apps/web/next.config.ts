import type { NextConfig } from 'next';

const nextConfig: NextConfig = process.env.SEENODE_BUILD === 'true'
  ? { output: 'standalone' }
  : {};

export default nextConfig;
