import type { Objective } from '@/lib/types';

interface ObjectivesPanelProps {
  objectives: Objective[];
}

export function ObjectivesPanel({ objectives }: ObjectivesPanelProps) {
  const active = objectives.filter(o => o.status === 'in_progress' || o.status === 'pending');

  return (
    <div className="panel flex flex-col">
      <div className="panel-header">
        <span>Current Objectives</span>
      </div>
      <div className="panel-body space-y-2">
        {active.length === 0 ? (
          <div className="text-text-tertiary text-xs italic">No active objectives</div>
        ) : (
          active.map((obj) => (
            <div key={obj.id} className="flex gap-2 text-xs">
              <span className="text-accent shrink-0">›</span>
              <div className="min-w-0">
                <span className="text-text-tertiary uppercase text-[10px] tracking-wide">
                  {obj.category}
                </span>
                <div className="text-text-primary">{obj.text}</div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
