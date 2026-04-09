import { useMemo } from 'react';

interface MapViewProps {
  tileGrid?: string[][];
  mapName?: string;
  position?: [number, number];
}

// Cell size — large enough to see detail
const CELL = 12;
const GRID_LINE = 0.5;

// Tile colors — high contrast, distinct types
const COLORS: Record<string, { fill: string; stroke?: string }> = {
  '.': { fill: '#e8e0d4', stroke: '#d0c8bc' },   // walkable — warm white
  '#': { fill: '#6b6b7b', stroke: '#5a5a6a' },   // wall — medium gray
  '~': { fill: '#7bc67b', stroke: '#6ab66a' },   // grass — green
  'W': { fill: '#5b9bd5', stroke: '#4a8ac4' },   // water — blue
  'P': { fill: '#e8e0d4' },                       // player tile (walkable underneath)
  'N': { fill: '#e8e0d4' },                       // NPC tile (walkable underneath)
  'D': { fill: '#e8e0d4', stroke: '#40c0e0' },   // door/warp — cyan border
  '?': { fill: '#2a2a35' },                       // unknown — dark
  'X': { fill: '#12121a' },                       // border — near black
};

// Player triangle facing down (default)
function PlayerMarker({ x, y, size }: { x: number; y: number; size: number }) {
  const cx = x + size / 2;
  const cy = y + size / 2;
  const s = size * 0.35;
  // Triangle pointing down
  const points = `${cx},${cy + s} ${cx - s},${cy - s * 0.6} ${cx + s},${cy - s * 0.6}`;
  return (
    <>
      {/* Glow */}
      <circle cx={cx} cy={cy} r={size * 0.45} fill="#e03030" opacity={0.15} />
      {/* Triangle */}
      <polygon points={points} fill="#1a1a2e" stroke="#e03030" strokeWidth={0.8} />
    </>
  );
}

// NPC marker
function NpcMarker({ x, y, size }: { x: number; y: number; size: number }) {
  const cx = x + size / 2;
  const cy = y + size / 2;
  const r = size * 0.3;
  return (
    <>
      {/* Body circle */}
      <circle cx={cx} cy={cy} r={r} fill="#f06090" stroke="#d04070" strokeWidth={0.6} />
      {/* Eyes */}
      <circle cx={cx - r * 0.35} cy={cy - r * 0.15} r={r * 0.18} fill="white" />
      <circle cx={cx + r * 0.35} cy={cy - r * 0.15} r={r * 0.18} fill="white" />
      <circle cx={cx - r * 0.35} cy={cy - r * 0.15} r={r * 0.09} fill="#1a1a2e" />
      <circle cx={cx + r * 0.35} cy={cy - r * 0.15} r={r * 0.09} fill="#1a1a2e" />
    </>
  );
}

export function MapView({ tileGrid, mapName, position }: MapViewProps) {
  const gridData = useMemo(() => {
    if (!tileGrid || tileGrid.length === 0) return null;
    // Trim border columns (X) and unknown rows from bottom
    const cols = Math.min(tileGrid[0].length, 18);
    // Find last non-unknown, non-border row
    let lastRow = tileGrid.length - 1;
    while (lastRow > 0) {
      const row = tileGrid[lastRow];
      const allHidden = row.slice(0, cols).every(c => c === '?' || c === 'X');
      if (!allHidden) break;
      lastRow--;
    }
    const rows = lastRow + 1;
    return { rows, cols, grid: tileGrid.slice(0, rows) };
  }, [tileGrid]);

  if (!gridData) {
    return (
      <div className="panel flex flex-col" style={{ minHeight: '160px' }}>
        <div className="panel-header">
          <span>Map</span>
        </div>
        <div className="panel-body flex-1 flex items-center justify-center">
          <span className="text-text-tertiary text-xs italic">No map data yet</span>
        </div>
      </div>
    );
  }

  const svgW = gridData.cols * CELL;
  const svgH = gridData.rows * CELL;

  return (
    <div className="panel flex flex-col" style={{ minHeight: '160px' }}>
      <div className="panel-header">
        <span>{mapName ?? 'Map'}</span>
        {position && (
          <span className="ml-auto text-[10px] text-text-secondary font-mono">
            [{position[0]},{position[1]}]
          </span>
        )}
      </div>
      <div
        className="flex-1 flex items-center justify-center min-h-0 p-2"
        style={{ background: '#12121a' }}
      >
        <svg
          viewBox={`0 0 ${svgW} ${svgH}`}
          className="w-full h-full"
          preserveAspectRatio="xMidYMid meet"
          style={{ borderRadius: '4px', overflow: 'hidden' }}
        >
          {/* Background */}
          <rect width={svgW} height={svgH} fill="#12121a" />

          {/* Tile cells */}
          {gridData.grid.map((row, y) =>
            row.slice(0, gridData.cols).map((cell, x) => {
              if (cell === 'X') return null;
              const colors = COLORS[cell] ?? COLORS['#'];
              return (
                <rect
                  key={`${y}-${x}`}
                  x={x * CELL + GRID_LINE}
                  y={y * CELL + GRID_LINE}
                  width={CELL - GRID_LINE * 2}
                  height={CELL - GRID_LINE * 2}
                  fill={colors.fill}
                  stroke={colors.stroke ?? 'none'}
                  strokeWidth={colors.stroke ? GRID_LINE : 0}
                  rx={cell === '#' ? 0 : 1}
                />
              );
            })
          )}

          {/* NPC markers (render on top of tiles) */}
          {gridData.grid.map((row, y) =>
            row.slice(0, gridData.cols).map((cell, x) => {
              if (cell === 'N') {
                return <NpcMarker key={`npc-${y}-${x}`} x={x * CELL} y={y * CELL} size={CELL} />;
              }
              return null;
            })
          )}

          {/* Player marker (render last, on top of everything) */}
          {gridData.grid.map((row, y) =>
            row.slice(0, gridData.cols).map((cell, x) => {
              if (cell === 'P') {
                return <PlayerMarker key={`player-${y}-${x}`} x={x * CELL} y={y * CELL} size={CELL} />;
              }
              return null;
            })
          )}

          {/* Grid lines overlay for structure */}
          {Array.from({ length: gridData.cols + 1 }).map((_, x) => (
            <line
              key={`vl-${x}`}
              x1={x * CELL} y1={0}
              x2={x * CELL} y2={svgH}
              stroke="#1a1a2e"
              strokeWidth={GRID_LINE * 0.5}
              opacity={0.3}
            />
          ))}
          {Array.from({ length: gridData.rows + 1 }).map((_, y) => (
            <line
              key={`hl-${y}`}
              x1={0} y1={y * CELL}
              x2={svgW} y2={y * CELL}
              stroke="#1a1a2e"
              strokeWidth={GRID_LINE * 0.5}
              opacity={0.3}
            />
          ))}
        </svg>
      </div>
    </div>
  );
}
