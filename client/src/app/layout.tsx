import type { Metadata } from "next";
import { Geist } from "next/font/google";
import { Shell } from "@/components/Shell";
import { VigilProvider } from "@/lib/store";
import "./globals.css";

const geist = Geist({ variable: "--font-geist-sans", subsets: ["latin"], weight: ["400", "500", "600"] });

export const metadata: Metadata = {
  title: "Vigil",
  description: "Health monitoring for astronaut wearables — compared with your own usual range.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={geist.variable} data-level="usual" suppressHydrationWarning>
      <body>
        <VigilProvider>
          <Shell>{children}</Shell>
        </VigilProvider>
      </body>
    </html>
  );
}
