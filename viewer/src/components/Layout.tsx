import type { ReactNode } from 'react';

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="h-screen w-screen flex flex-col bg-bg-primary overflow-hidden">
      {children}
    </div>
  );
}
