import type { Metadata } from "next";
import type { ReactNode } from "react";
import "@fontsource-variable/dm-sans";
import "@fontsource-variable/space-grotesk";
import "@fontsource-variable/geist-mono";
import { Shell } from "@/components/shell";
import "./styles.css";
import "./controls.css";

export const metadata: Metadata = {
  title: "ChipCheck Console",
  description: "ActiveQual research console: contracts, fixtures, campaigns and results",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body><Shell>{children}</Shell></body>
    </html>
  );
}
