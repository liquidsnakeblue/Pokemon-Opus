import type { Objective } from '@/lib/types';

interface ObjectivesPanelProps {
  objectives: Objective[];
}

const STATUS_ICONS: Record<string, string> = {
  in_progress: '●',
  pending: '○',
  completed: '✓',
  abandoned: '✗',
};

const CATEGORY_COLORS: Record<string, string> = {
  progression: 'text-accent-bright',
  battle: 'text-type-fire',
  exploration: 'text-type-grass',
  collection: 'text-type-electric',
};

export function ObjectivesPanel({ objectives }: ObjectivesPanelProps) {
  const active = objectives.filter(o => o.status === 'in_progress' || o.status === 'pending');

  return (
    <div className="panel flex-1 min-h-0 flex flex-col">
      <div className="panel-header">
        <span>Objectives</span>
        <span className="ml-auto text-[10px] text-text-tertiary">{active.length} active</span>
      </div>
      <div className="panel-body flex-1 overflow-y-auto space-y-2">
        {active.length === 0 ? (
          <div className="text-text-tertiary text-xs italic">No active objectives</div>
        ) : (
          active.map((obj, i) => (
            <div key={obj.id} className="flex gap-2 text-xs slide-in">
              <span className={`text-sm ${CATEGORY_COLORS[obj.category] ?? 'text-text-secondary'}`}>
                {i + 1}
              </span>
              <div className="flex-1 min-w-0">
                <div className="font-medium text-text-primary">
                  {obj.name}
                </div>
                <div className="text-text-tertiary mt-0.5 leading-relaxed">
                  {obj.text}
                </div>
              </div>
              <span className="text-text-tertiary text-[10px] shrink-0">
                {STATUS_ICONS[obj.status] ?? '?'}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
