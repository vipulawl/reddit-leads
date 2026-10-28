import "./globals.css";

export const metadata = { title: "reddit-leads", description: "Find buyers on Reddit in near real time" };

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
