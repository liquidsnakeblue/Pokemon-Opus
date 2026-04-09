import type { Pokemon } from '@/lib/types';
import { TYPE_COLORS } from '@/lib/types';

interface TeamPanelProps {
  party: Pokemon[];
}

function spriteUrl(speciesId: number): string {
  return `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/${speciesId}.png`;
}

export function TeamPanel({ party }: TeamPanelProps) {
  return (
    <div className="panel flex flex-col">
      <div className="panel-header">
        <span>Team</span>
        <span className="ml-auto text-[10px] text-text-tertiary font-normal">
          {party.length > 0 ? `${party.length}/6` : ''}
        </span>
      </div>
      <div className="flex items-center gap-2 p-2">
        {party.length === 0 ? (
          // Empty slots
          Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="w-9 h-9 rounded-full" style={{ background: '#141e33', border: '2px solid #1e2d4a' }} />
          ))
        ) : (
          party.map((mon, i) => (
            <div key={i} className="flex flex-col items-center gap-0.5" title={`${mon.species} Lv${mon.level}`}>
              <div className="relative">
                <img
                  src={spriteUrl(mon.species_id)}
                  alt={mon.species}
                  className="w-10 h-10"
                  style={{ imageRendering: 'pixelated' }}
                  loading="lazy"
                  onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                />
                <span className="absolute -bottom-0.5 left-0 right-0 text-center text-[8px] font-bold text-text-primary bg-bg-panel/80 rounded px-0.5">
                  Lv{mon.level}
                </span>
              </div>
              {/* HP bar */}
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
          ))
        )}

        {/* Pokedex count */}
        <div className="ml-auto flex flex-col items-end text-[10px]">
          <span className="text-text-primary font-bold">{party.length > 0 ? party.length : '0'}</span>
          <span className="text-text-tertiary">DEX</span>
        </div>
      </div>
    </div>
  );
}
