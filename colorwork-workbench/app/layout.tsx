import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: '库存色块图调整台',
  description: '选择产品、Radio、颜色和尺寸，生成并管理库存配色图。',
  robots: { index: false, follow: false, nocache: true },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
