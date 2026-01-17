/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://sentellent-alb-2048283287.ap-south-1.elb.amazonaws.com/:path*",
      },
    ];
  },
};

module.exports = nextConfig;
