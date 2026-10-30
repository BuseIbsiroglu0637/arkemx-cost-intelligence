import type { NextConfig } from 'next';
const desktop = process.env.ARKEMX_DESKTOP_BUILD === '1';
const nextConfig: NextConfig = {
  reactStrictMode: true,
  ...(desktop ? { output: 'export', trailingSlash: true, distDir: '.next-desktop' } : {}),
};
export default nextConfig;
