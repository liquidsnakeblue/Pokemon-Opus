interface StatsBarProps {
  connected: boolean;
  viewers: number;
  turn: number;
  mode: string;
  runtime: string;
  tokens: number;
  cost: number;
  mapName: string;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

const MODE_LABELS: Record<string, { label: string; color: string }> = {
  explore: { label: 'EXPLORING', color: 'text-type-grass' },
  battle: { label: 'BATTLE', color: 'text-type-fire' },
  dialog: { label: 'DIALOG', color: 'text-type-electric' },
  menu: { label: 'MENU', color: 'text-text-tertiary' },
};

export function StatsBar({
  connected,
  viewers,
  turn,
  mode,
  runtime,
  tokens,
  cost,
  mapName,
}: StatsBarProps) {
  const modeInfo = MODE_LABELS[mode] ?? MODE_LABELS.explore;

  return (
    <div className="flex items-center justify-between gap-4 px-3 py-2 rounded-lg bg-bg-panel border border-border text-xs font-mono">
      {/* Left: title + connection */}
      <div className="flex items-center gap-3">
        <span className="text-accent-bright font-bold text-sm tracking-wider">
          POKEMON-OPUS
        </span>
        <span className={`w-2 h-2 rounded-full ${connected ? 'bg-hp-green' : 'bg-hp-red'}`} />
        {connected && (
          <span className="text-text-tertiary">{viewers} viewer{viewers !== 1 ? 's' : ''}</span>
        )}
      </div>

      {/* Center: stats */}
      <div className="flex items-center gap-6 text-text-secondary">
        <Stat label="Turn" value={String(turn)} />
        <Stat label="Mode" value={modeInfo.label} className={modeInfo.color} />
        <Stat label="Location" value={mapName} />
        <Stat label="Runtime" value={runtime} />
        <Stat label="Tokens" value={formatTokens(tokens)} />
        <Stat label="Cost" value={`$${cost.toFixed(2)}`} />
      </div>

      {/* Right: live indicator */}
      <div className="flex items-center gap-2">
        {connected && (
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-hp-red animate-pulse" />
            <span className="text-hp-red font-bold text-[10px]">LIVE</span>
          </span>
        )}
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  className = '',
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-text-tertiary">{label}</span>
      <span className={`text-text-primary font-semibold ${className}`}>{value}</span>
    </div>
  );
}
