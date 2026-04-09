import { BADGES } from '@/lib/types';
import type { Milestone } from '@/lib/types';

interface BadgeTimelineProps {
  badges: string[];
  milestones: Milestone[];
}

export function BadgeTimeline({ badges, milestones }: BadgeTimelineProps) {
  const badgeSet = new Set(badges);

  return (
    <div className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-bg-panel border border-border">
      {BADGES.map((badge, i) => {
        const earned = badgeSet.has(badge.name);
        const milestone = milestones.find(
          m => m.category === 'badge' && m.name.includes(badge.name)
        );

        return (
          <div key={badge.name} className="flex items-center gap-1">
            {/* Badge circle */}
            <div
              className="relative group"
              title={`${badge.name} Badge${milestone ? ` (Turn ${milestone.turn})` : ''}`}
            >
              <div
                className={`w-7 h-7 rounded-full border-2 flex items-center justify-center text-[9px] font-bold transition-all ${
                  earned
                    ? 'border-transparent shadow-[0_0_8px_rgba(255,255,255,0.2)]'
                    : 'border-border opacity-40'
                }`}
                style={earned ? { backgroundColor: badge.color } : undefined}
              >
                {earned ? '✓' : i + 1}
              </div>
              {/* Tooltip */}
              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 px-2 py-0.5 rounded bg-bg-secondary border border-border text-[10px] text-text-secondary whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10">
                {badge.name}
                {milestone && <span className="text-text-tertiary ml-1">T{milestone.turn}</span>}
              </div>
            </div>

            {/* Connector line */}
            {i < BADGES.length - 1 && (
              <div
                className={`w-6 h-0.5 ${
                  earned && badgeSet.has(BADGES[i + 1]?.name ?? '')
                    ? 'bg-accent'
                    : 'bg-border'
                }`}
              />
            )}
          </div>
        );
      })}

      {/* Badge count */}
      <span className="ml-3 text-xs text-text-tertiary font-mono">
        {badges.length}/8
      </span>
    </div>
  );
}
