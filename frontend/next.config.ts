import type { NextConfig } from "next";

// NEXT_PUBLIC_* 会在构建时写入浏览器 bundle；缺失时应在 config/build 阶段失败，
// 而不是让浏览器运行后请求 `undefined/...`。
if (!process.env.NEXT_PUBLIC_API_URL?.trim()) {
  throw new Error("NEXT_PUBLIC_API_URL is required");
}

const nextConfig: NextConfig = {
  /* config options here */
};

export default nextConfig;
