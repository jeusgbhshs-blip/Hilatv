import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";

import { ThemeProvider } from "@/components/theme/theme-provider";
import { ThemeScript } from "@/components/theme/theme-script";

import "./globals.css";

// Noto Sans SC (SIL OFL 1.1), self-hosted subset: GB2312 level-1 hanzi, CJK
// punctuation, ASCII and every character in this app. Not loaded from Google Fonts.
const notoSansSC = localFont({
  src: [
    { path: "../public/fonts/NotoSansSC-Regular-subset.woff2", weight: "400", style: "normal" },
    { path: "../public/fonts/NotoSansSC-Medium-subset.woff2", weight: "500", style: "normal" },
  ],
  variable: "--font-noto-sc",
  display: "swap",
  preload: false,
  fallback: ["PingFang SC", "Microsoft YaHei", "system-ui", "sans-serif"],
});

export const metadata: Metadata = {
  title: "HiLatv",
  description: "企业一句话，生成可发布的商业短视频",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "rgb(245,245,247)" },
    { media: "(prefers-color-scheme: dark)", color: "rgb(12,12,14)" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    // data-theme is set by ThemeScript before first paint, so the server markup differs on purpose.
    <html lang="zh-CN" className={notoSansSC.variable} suppressHydrationWarning>
      <head>
        <ThemeScript />
      </head>
      <body className="antialiased">
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
