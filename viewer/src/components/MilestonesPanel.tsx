import type { Milestone } from '@/lib/types';

interface MilestonesPanelProps {
  milestones: Milestone[];
}

export function MilestonesPanel({ milestones }: MilestonesPanelProps) {
  const sorted = [...milestones].reverse();

  return (
    <div className="panel flex flex-col">
      <div className="panel-header">
        <span>Milestones</span>
      </div>
      <div className="panel-body flex-1 overflow-y-auto">
        {sorted.length === 0 ? (
          <div className="text-text-tertiary text-xs italic">No milestones yet</div>
        ) : (
          <div className="space-y-1.5 text-xs">
            {sorted.map((m, i) => (
              <div key={`${m.name}-${m.turn}-${i}`} className="flex items-center justify-between gap-2">
                <span className="text-text-primary truncate">{m.name}</span>
                <span className="text-accent font-mono text-[10px] shrink-0">Turn {m.turn.toLocaleString()}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
