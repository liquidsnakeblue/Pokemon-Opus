import type { Pokemon } from '@/lib/types';
import { TYPE_COLORS } from '@/lib/types';

interface TeamPanelProps {
  party: Pokemon[];
}

function hpColor(hp: number, maxHp: number): string {
  if (maxHp === 0) return 'bg-border';
  const pct = hp / maxHp;
  if (pct > 0.5) return 'bg-hp-green';
  if (pct > 0.2) return 'bg-hp-yellow';
  return 'bg-hp-red';
}

function spriteUrl(speciesId: number): string {
  return `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/${speciesId}.png`;
}

export function TeamPanel({ party }: TeamPanelProps) {
  // Pad to 6 slots
  const slots = [...party, ...Array(Math.max(0, 6 - party.length)).fill(null)];

  return (
    <div className="panel">
      <div className="panel-header">
        <span>Team</span>
        <span className="ml-auto text-[10px] text-text-tertiary">{party.length}/6</span>
      </div>
      <div className="grid grid-cols-6 gap-1 p-2">
        {slots.map((pokemon: Pokemon | null, i: number) => (
          <PokemonCard key={i} pokemon={pokemon} />
        ))}
      </div>
    </div>
  );
}

function PokemonCard({ pokemon }: { pokemon: Pokemon | null }) {
  if (!pokemon) {
    return (
      <div className="flex flex-col items-center p-1 rounded bg-bg-secondary border border-border opacity-30 min-h-[100px]">
        <div className="w-10 h-10 rounded-full bg-bg-panel mt-2" />
      </div>
    );
  }

  const hpPct = pokemon.max_hp > 0 ? (pokemon.hp / pokemon.max_hp) * 100 : 0;
  const displayName = pokemon.nickname && pokemon.nickname !== pokemon.species
    ? pokemon.nickname
    : pokemon.species;

  return (
    <div className="flex flex-col items-center p-1.5 rounded bg-bg-secondary border border-border min-h-[100px]">
      {/* Sprite */}
      <img
        src={spriteUrl(pokemon.species_id)}
        alt={pokemon.species}
        className="w-10 h-10"
        style={{ imageRendering: 'pixelated' }}
        loading="lazy"
        onError={(e) => {
          (e.target as HTMLImageElement).style.display = 'none';
        }}
      />

      {/* Name + Level */}
      <div className="text-[10px] font-semibold text-text-primary truncate w-full text-center mt-0.5">
        {displayName}
      </div>
      <div className="text-[9px] text-text-tertiary">Lv{pokemon.level}</div>

      {/* Type badges */}
      <div className="flex gap-0.5 mt-0.5">
        {pokemon.types.map(type => (
          <span
            key={type}
            className="text-[7px] font-bold px-1 rounded text-white"
            style={{ backgroundColor: TYPE_COLORS[type] ?? '#888' }}
          >
            {type.slice(0, 3).toUpperCase()}
          </span>
        ))}
      </div>

      {/* HP bar */}
      <div className="w-full mt-1">
        <div className="hp-bar-bg">
          <div
            className={`hp-bar-fill ${hpColor(pokemon.hp, pokemon.max_hp)}`}
            style={{ width: `${hpPct}%` }}
          />
        </div>
        <div className="text-[8px] text-text-tertiary text-center mt-0.5">
          {pokemon.hp}/{pokemon.max_hp}
        </div>
      </div>

      {/* Status */}
      {pokemon.status !== 'OK' && (
        <span className="text-[8px] font-bold text-hp-red mt-0.5">
          {pokemon.status}
        </span>
      )}
    </div>
  );
}
