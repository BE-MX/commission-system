import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host") ?? "localhost:3000";
  const protocol = requestHeaders.get("x-forwarded-proto") ?? (host.includes("localhost") ? "http" : "https");
  const image = `${protocol}://${host}/leshine-brand.jpg`;
  const title = "莱莎健康假发｜零售商城与批发商城";
  const description = "莱莎健康假发独立零售商城、批发商分级商城与经营管理后台。";
  return {
    title, description,
    icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
    openGraph: { title, description, images: [{ url: image, width: 1808, height: 1664, alt: "莱莎健康假发品牌形象" }] },
    twitter: { card: "summary_large_image", title, description, images: [image] },
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
