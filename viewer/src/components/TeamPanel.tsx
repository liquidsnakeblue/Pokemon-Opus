import type { Pokemon } from '@/lib/types';
import { TYPE_COLORS } from '@/lib/types';

interface TeamPanelProps {
  party: Pokemon[];
}

function spriteUrl(speciesId: number): string {
  return `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/${speciesId}.png`;
}

export function TeamPanel({ party }: TeamPanelProps) {
  const slots = [...party, ...Array(Math.max(0, 6 - party.length)).fill(null)];

  return (
    <div className="panel flex flex-col shrink-0">
      <div className="panel-header">
        <span>Team</span>
        <span className="ml-auto text-[10px] text-text-tertiary font-normal">
          {party.length}/6
        </span>
      </div>
      <div className="flex items-center justify-center gap-3 px-3 py-2">
        {slots.map((mon: Pokemon | null, i: number) =>
          mon ? (
            <div key={i} className="flex flex-col items-center gap-0.5" title={`${mon.species} Lv${mon.level}`}>
              <img
                src={spriteUrl(mon.species_id)}
                alt={mon.species}
                className="w-10 h-10"
                style={{ imageRendering: 'pixelated' }}
                loading="lazy"
                onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
              />
              <span className="text-[8px] font-bold text-text-primary">Lv{mon.level}</span>
              <div className="w-10 hp-bar">
                <div
                  className="hp-bar-fill"
                  style={{
                    width: `${mon.max_hp > 0 ? (mon.hp / mon.max_hp) * 100 : 0}%`,
                    backgroundColor: mon.max_hp > 0
                      ? mon.hp / mon.max_hp > 0.5 ? '#22c55e' : mon.hp / mon.max_hp > 0.2 ? '#eab308' : '#ef4444'
                      : '#1e2d4a',
                  }}
                />
              </div>
            </div>
          ) : (
            <div key={i} className="w-8 h-8 rounded-full" style={{ background: '#141e33', border: '2px solid #1e2d4a' }} />
          )
        )}
      </div>
    </div>
  );
}
