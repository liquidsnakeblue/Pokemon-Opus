import type { Milestone } from '@/lib/types';

interface MilestonesPanelProps {
  milestones: Milestone[];
}

const CATEGORY_ICONS: Record<string, string> = {
  badge: '🏅',
  catch: '⚾',
  item: '🎒',
  level: '⬆️',
  progression: '🎯',
  general: '✦',
};

export function MilestonesPanel({ milestones }: MilestonesPanelProps) {
  // Show most recent first
  const sorted = [...milestones].reverse();

  return (
    <div className="panel flex-1 min-h-0 flex flex-col">
      <div className="panel-header">
        <span>Milestones</span>
        <span className="ml-auto text-[10px] text-text-tertiary">{milestones.length}</span>
      </div>
      <div className="panel-body flex-1 overflow-y-auto">
        {sorted.length === 0 ? (
          <div className="text-text-tertiary text-xs italic">No milestones yet</div>
        ) : (
          <div className="space-y-1">
            {sorted.map((m, i) => (
              <div key={`${m.name}-${m.turn}-${i}`} className="milestone-item">
                <span className="text-sm">
                  {CATEGORY_ICONS[m.category] ?? CATEGORY_ICONS.general}
                </span>
                <span className="flex-1 text-text-primary truncate">{m.name}</span>
                <span className="milestone-turn">T{m.turn}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
