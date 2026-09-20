import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow the dev server's HMR / RSC chunks to be loaded when the browser
  // is on `127.0.0.1` — Kite's OAuth redirect can land there even though
  // the canonical dev origin is `localhost`. Without this, Next 16 blocks
  // the cross-origin dev-resource fetch and the callback page can't
  // finish loading.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
};

export default nextConfig;
