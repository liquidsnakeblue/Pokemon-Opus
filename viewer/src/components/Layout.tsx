import type { ReactNode } from 'react';

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="h-screen w-screen grid grid-rows-[auto_1fr] grid-cols-[1fr_auto_1fr] gap-2 p-2 bg-bg-primary overflow-hidden">
      {children}
    </div>
  );
}
