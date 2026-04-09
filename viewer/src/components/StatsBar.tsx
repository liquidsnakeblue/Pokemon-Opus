import { BADGES } from '@/lib/types';

interface StatsBarProps {
  connected: boolean;
  viewers: number;
  turn: number;
  mode: string;
  runtime: string;
  tokens: number;
  cost: number;
  mapName: string;
  badges: string[];
}

function formatTokens(n: number): string {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

const MODE_COLORS: Record<string, string> = {
  explore: '#78c850',
  battle: '#f08030',
  dialog: '#f8d030',
  menu: '#506080',
};

export function StatsBar({
  connected, viewers, turn, mode, runtime, tokens, cost, mapName, badges,
}: StatsBarProps) {
  const badgeSet = new Set(badges);

  return (
    <div className="flex items-center gap-3 px-4 py-2">
      {/* Title */}
      <div className="flex items-center gap-2 mr-2">
        <span className="text-accent font-bold text-sm tracking-[0.15em]">POKEMON-OPUS</span>
        <span className={`w-2 h-2 rounded-full ${connected ? 'bg-hp-green' : 'bg-hp-red'}`} />
      </div>

      {/* Stats */}
      <div className="stat-pill">
        <span className="label">Cash</span>
        <span className="value">₽0</span>
      </div>
      <div className="stat-pill">
        <span className="label">Turns</span>
        <span className="value">{turn.toLocaleString()}</span>
      </div>
      <div className="stat-pill">
        <span className="label">Tokens</span>
        <span className="value">{formatTokens(tokens)}</span>
      </div>
      <div className="stat-pill">
        <span className="label">Time</span>
        <span className="value">{runtime}</span>
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Badges */}
      <div className="flex items-center gap-1">
        {BADGES.map((badge) => {
          const earned = badgeSet.has(badge.name);
          return (
            <div
              key={badge.name}
              className="w-5 h-5 rounded-full flex items-center justify-center"
              style={{
                backgroundColor: earned ? badge.color : '#141e33',
                border: `2px solid ${earned ? badge.color : '#1e2d4a'}`,
                boxShadow: earned ? `0 0 6px ${badge.color}60` : 'none',
              }}
              title={`${badge.name} Badge`}
            />
          );
        })}
      </div>

      {/* Mode + Location */}
      <div className="flex items-center gap-2 ml-2">
        <span
          className="text-[10px] font-bold px-2 py-0.5 rounded uppercase"
          style={{
            color: MODE_COLORS[mode] ?? '#506080',
            background: `${MODE_COLORS[mode] ?? '#506080'}20`,
          }}
        >
          {mode}
        </span>
        {connected && (
          <span className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-hp-red animate-pulse" />
            <span className="text-[10px] text-hp-red font-bold">LIVE</span>
          </span>
        )}
      </div>
    </div>
  );
}
