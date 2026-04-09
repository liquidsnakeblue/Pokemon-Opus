import type { ReactNode } from 'react';

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="h-screen w-screen grid grid-rows-[auto_1fr] grid-cols-[280px_1fr_280px] gap-2 p-2 bg-bg-primary">
      {children}
    </div>
  );
}
