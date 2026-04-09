import { useMemo } from 'react';

interface MapViewProps {
  tileGrid?: string[][];
  mapName?: string;
  position?: [number, number];
}

// Tile type → color mapping
const TILE_COLORS: Record<string, string> = {
  '.': '#2a3a2a',   // walkable floor — dark green
  '#': '#1a1a2e',   // wall — dark blue-gray
  '~': '#1a4a1a',   // grass — brighter green
  'W': '#1a2a4a',   // water — blue
  'P': '#e03030',   // player — red
  'N': '#e0a030',   // NPC — yellow/orange
  'D': '#30a0e0',   // door/warp — cyan
  '?': '#0a0a14',   // unknown (dialog overlay) — near black
  'X': '#050510',   // border — black
};

const CELL_SIZE = 4;

export function MapView({ tileGrid, mapName, position }: MapViewProps) {
  const hasData = tileGrid && tileGrid.length > 0 && tileGrid[0].length > 0;

  // Only render the inner 18 columns (skip border X columns)
  const gridData = useMemo(() => {
    if (!hasData) return null;
    const rows = tileGrid.length;
    const cols = Math.min(tileGrid[0].length, 18); // trim border columns
    return { rows, cols, grid: tileGrid };
  }, [tileGrid, hasData]);

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

  const svgW = gridData.cols * CELL_SIZE;
  const svgH = gridData.rows * CELL_SIZE;

  return (
    <div className="panel flex flex-col" style={{ minHeight: '160px' }}>
      <div className="panel-header">
        <span>Map</span>
        <span className="ml-auto text-[10px] text-text-tertiary font-normal">
          {mapName ?? ''}
        </span>
      </div>
      <div className="flex-1 flex items-center justify-center min-h-0 p-1" style={{ background: '#050510' }}>
        <svg
          viewBox={`0 0 ${svgW} ${svgH}`}
          className="w-full h-full"
          preserveAspectRatio="xMidYMid meet"
        >
          {gridData.grid.map((row, y) =>
            row.slice(0, gridData.cols).map((cell, x) => {
              const color = TILE_COLORS[cell] ?? TILE_COLORS['#'];
              // Skip rendering pure-black border/unknown cells for performance
              if (cell === 'X') return null;
              return (
                <rect
                  key={`${y}-${x}`}
                  x={x * CELL_SIZE}
                  y={y * CELL_SIZE}
                  width={CELL_SIZE}
                  height={CELL_SIZE}
                  fill={color}
                />
              );
            })
          )}
          {/* Player glow effect */}
          {gridData.grid.map((row, y) =>
            row.slice(0, gridData.cols).map((cell, x) => {
              if (cell !== 'P') return null;
              return (
                <circle
                  key={`glow-${y}-${x}`}
                  cx={x * CELL_SIZE + CELL_SIZE / 2}
                  cy={y * CELL_SIZE + CELL_SIZE / 2}
                  r={CELL_SIZE * 1.2}
                  fill="#e03030"
                  opacity={0.25}
                />
              );
            })
          )}
        </svg>
      </div>
      {/* Footer */}
      {position && (
        <div className="flex items-center justify-between px-2 py-1 text-[10px] font-mono border-t border-white/5">
          <span className="text-text-tertiary">
            ({position[0]}, {position[1]})
          </span>
        </div>
      )}
    </div>
  );
}
