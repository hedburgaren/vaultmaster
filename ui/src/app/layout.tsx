import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'VaultMaster — Backup Control Center',
  description: 'Self-hosted backup orchestration for ARC Gruppen',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="sv">
      <body className="min-h-screen">{children}</body>
    </html>
  )
}
