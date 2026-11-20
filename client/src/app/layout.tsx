import type { Metadata } from "next";
import { Geist } from "next/font/google";
import { Shell } from "@/components/Shell";
import { I18nProvider } from "@/i18n";
import { VigilProvider } from "@/lib/store";
import "./globals.css";

const geist = Geist({ variable: "--font-geist-sans", subsets: ["latin", "cyrillic"], weight: ["400", "500", "600"] });

export const metadata: Metadata = {
  title: "Vigil",
  description: "Health monitoring for astronaut wearables — compared with your own usual range.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={geist.variable} data-level="usual" suppressHydrationWarning>
      <body>
        <I18nProvider>
          <VigilProvider>
            <Shell>{children}</Shell>
          </VigilProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
