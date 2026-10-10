import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The app is fully client-side; the API is a separate service.
  output: "export",
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
