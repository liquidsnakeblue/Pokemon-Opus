import { useEffect, useRef } from 'react';

interface ReasoningPanelProps {
  reasoning: string;
  turn: number;
}

export function ReasoningPanel({ reasoning, turn }: ReasoningPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [reasoning]);

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
      <div ref={scrollRef} className="panel-body flex-1 overflow-y-auto">
        {reasoning ? (
          <div className="reasoning-text">{reasoning}</div>
        ) : (
          <div className="text-text-tertiary text-sm italic">
            Waiting for AI reasoning...
          </div>
        )}
      </div>
    </div>
  );
}
