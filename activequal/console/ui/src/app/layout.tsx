import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "ChipCheck Console",
  description: "Configure a hardware test setup and review proposed tests"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
