import type { Metadata } from "next";
import "./globals.css";

import { ChatProvider } from "@/context/ChatContext";

export const metadata: Metadata = {
  title: "AI Chat",
  description: "AI Chat Application",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className="
          min-h-screen
          antialiased
        "
      >
        <ChatProvider>{children}</ChatProvider>
      </body>
    </html>
  );
}
