/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  // Proxy API requests to the FastAPI backend in development
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/:path*`,
      },
    ];
  },

  // Images: allow avatar / agent icon hosting
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**.agentx.io" },
      { protocol: "http",  hostname: "localhost" },
    ],
  },
};

export default nextConfig;
