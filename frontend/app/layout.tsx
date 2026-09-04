import "./globals.css";

export const metadata = {
  title: "Digital Shelf Monitoring",
  description: "Auditoría y Monitoreo Multibanner",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}