import type { Metadata } from "next";
import { Noto_Sans_Devanagari, Roboto } from "next/font/google";
import "./globals.css";

const roboto = Roboto({
  variable: "--font-roboto",
  subsets: ["latin"],
  weight: ["400", "500", "700"],
});

// Roboto has no Hindi letters; this carries the advisor's Hindi answers.
const devanagari = Noto_Sans_Devanagari({
  variable: "--font-devanagari",
  subsets: ["devanagari"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "homesol",
  description: "Rooftop solar planning for Indian homes",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${roboto.variable} ${devanagari.variable} h-full antialiased`}
    >
      <head>
        {/* Icons used across the app. */}
        {/* eslint-disable-next-line @next/next/no-page-custom-font, @next/next/google-font-display -- root layout, so it applies to every page; icons must not flash as text */}
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,400,0,0&display=block"
        />
      </head>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
