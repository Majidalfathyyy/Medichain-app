import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'MediChain | Layanan kesehatan terhubung',
  description: 'Ruang kerja klinis dan administrasi MediChain.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="id"><body>{children}</body></html>;
}
