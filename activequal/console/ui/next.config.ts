import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  devIndicators: false,
  // The icon package re-exports every icon; import only what is used.
  experimental: { optimizePackageImports: ["@phosphor-icons/react"] },
};
export default nextConfig;
