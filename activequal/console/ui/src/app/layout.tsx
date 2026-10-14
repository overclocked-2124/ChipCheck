import type { Metadata } from "next";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "@fontsource-variable/newsreader";
import "./styles.css";

export const metadata: Metadata = {
  title: "ChipCheck Console",
  description: "Configure a hardware test setup and review proposed tests"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
