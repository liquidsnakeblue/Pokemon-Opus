import { useEffect, useRef } from 'react';
import type { ReasoningEntry } from '@/hooks/useWebSocket';

interface ReasoningPanelProps {
  reasoning: string;
  reasoningHistory: ReasoningEntry[];
  turn: number;
}

export function ReasoningPanel({ reasoning, reasoningHistory, turn }: ReasoningPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [reasoning, reasoningHistory]);

  return (
    <div className="panel flex-1 flex flex-col min-h-0">
      <div className="panel-header">
        <span>Log</span>
        <div className="ml-auto flex items-center gap-3 text-[10px]">
          <span className="text-text-tertiary">TOTAL TIME</span>
          <span className="text-text-secondary font-mono">—</span>
        </div>
      </div>
      <div ref={scrollRef} className="panel-body flex-1 overflow-y-auto space-y-4">
        {/* Turn counter */}
        {turn > 0 && (
          <div className="text-center text-2xl font-bold text-text-primary opacity-30">
            {turn.toLocaleString()}
          </div>
        )}

        {reasoningHistory.map((entry, i) => (
          <div key={i} className="space-y-1">
            {entry.actions && entry.actions.length > 0 && (
              <div className="text-[10px] text-text-tertiary font-mono">
                {entry.actions.map((a, j) => (
                  <span key={j}>
                    {j > 0 && ', '}
                    <span className="px-1 py-0.5 rounded bg-bg-secondary text-accent">{a}</span>
                  </span>
                ))}
              </div>
            )}
            <div className="text-xs text-text-secondary leading-relaxed">{entry.text}</div>
          </div>
        ))}

        {/* In-progress reasoning */}
        {reasoning && reasoningHistory.length > 0 &&
          reasoningHistory[reasoningHistory.length - 1]?.text !== reasoning && (
          <div className="text-xs text-text-secondary leading-relaxed opacity-60">
            {reasoning}
          </div>
        )}

        {reasoningHistory.length === 0 && !reasoning && (
          <div className="text-text-tertiary text-xs italic text-center mt-4">
            Waiting for AI reasoning...
          </div>
        )}
      </div>
    </div>
  );
}
