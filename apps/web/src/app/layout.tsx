import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Blindspot Lab: Understand What You Don't Understand",
  description:
    "A source-grounded AI learning platform that uncovers misconceptions, investigates reasoning, repairs understanding and tests transfer.",
};

export const viewport: Viewport = { themeColor: "#060a13" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="min-h-screen">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
