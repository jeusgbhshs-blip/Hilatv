import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "HiLatv",
  description: "企业一句话，生成可发布的商业短视频",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="antialiased">{children}</body>
    </html>
  );
}
