import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ARKEMX Cost Intelligence | M1",
  description: "Review-first metraj intake and source-traceable cost intelligence"
};
export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="tr"><body>{children}</body></html>;
}
