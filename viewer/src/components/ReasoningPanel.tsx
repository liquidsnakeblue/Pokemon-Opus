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
    <div className="panel h-full flex flex-col">
      <div className="panel-header">
        <span className="text-accent-bright">✦</span>
        <span>Reasoning</span>
        {turn > 0 && (
          <span className="ml-auto text-[10px] text-text-tertiary font-mono">
            Turn {turn}
          </span>
        )}
      </div>
      <div ref={scrollRef} className="panel-body flex-1 overflow-y-auto space-y-3">
        {reasoningHistory.map((entry, i) => (
          <div key={i} className="border-b border-white/5 pb-2 last:border-0">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[10px] font-mono text-accent-bright font-bold">T{entry.turn}</span>
              {entry.actions && (
                <span className="text-[10px] font-mono text-text-tertiary truncate">
                  {entry.actions.join(' → ')}
                </span>
              )}
            </div>
            <div className="text-xs text-text-secondary leading-relaxed">{entry.text}</div>
          </div>
        ))}
        {reasoning && reasoningHistory.length > 0 &&
          reasoningHistory[reasoningHistory.length - 1]?.text !== reasoning && (
          <div className="text-xs text-text-secondary leading-relaxed animate-pulse">
            {reasoning}
          </div>
        )}
        {reasoningHistory.length === 0 && !reasoning && (
          <div className="text-text-tertiary text-sm italic">
            Waiting for AI reasoning...
          </div>
        )}
      </div>
    </div>
  );
}
