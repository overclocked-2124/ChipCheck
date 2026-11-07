import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Shell } from "@/components/shell";
import "./styles.css";

export const metadata: Metadata = {
  title: "ActiveQual Console",
  description: "Adaptive physical testing: contracts, fixtures, campaigns and results",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body><Shell>{children}</Shell></body>
    </html>
  );
}
