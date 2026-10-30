import type { Metadata } from "next";
import Link from "next/link";

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
      <body className="antialiased">
        <div className="min-h-screen">
          <header className="border-b border-border">
            <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-3 px-4">
              <Link href="/" className="text-sm font-semibold tracking-wide">
                HiLatv
              </Link>
              <nav className="flex items-center gap-4 text-sm">
                <Link href="/brand">品牌资料</Link>
                <Link href="/concepts">方案</Link>
                <p className="text-muted-foreground">一句成片</p>
              </nav>
            </div>
          </header>
          <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:py-12">{children}</main>
        </div>
      </body>
    </html>
  );
}
