import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Chat Frontend",
  description: "Starter interface for the chat application"
};

export default function RootLayout({
  children
}: {
  children: React.ReactNode;
}): JSX.Element {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
