import { useWebSocket } from '@/hooks/useWebSocket';
import { Layout } from '@/components/Layout';
import { GameScreen } from '@/components/GameScreen';
import { ReasoningPanel } from '@/components/ReasoningPanel';
import { TeamPanel } from '@/components/TeamPanel';
import { ObjectivesPanel } from '@/components/ObjectivesPanel';
import { InventoryPanel } from '@/components/InventoryPanel';
import { StatsBar } from '@/components/StatsBar';
import { MilestonesPanel } from '@/components/MilestonesPanel';
import { MapView } from '@/components/MapView';

export default function App() {
  const { connected, viewers, gameState, screenshot, reasoning, reasoningHistory, events } =
    useWebSocket();

  return (
    <Layout>
      {/* Header */}
      <div className="shrink-0">
        <StatsBar
          connected={connected}
          viewers={viewers}
          turn={gameState?.turn ?? 0}
          mode={gameState?.mode ?? 'explore'}
          runtime={gameState?.performance.runtime ?? '0:00:00'}
          tokens={gameState?.performance.total_tokens ?? 0}
          cost={gameState?.performance.total_cost_usd ?? 0}
          mapName={gameState?.player.map_name ?? '—'}
          badges={gameState?.player.badges ?? []}
        />
      </div>

      {/* Main content: 3 columns */}
      <div className="flex-1 flex gap-3 px-4 pb-3 min-h-0 overflow-hidden">
        {/* Left: Game + Map + Team — fixed proportions */}
        <div className="flex flex-col gap-2 w-[480px] shrink-0 min-h-0 overflow-y-auto">
          <div className="shrink-0">
            <GameScreen mode={gameState?.mode ?? 'explore'} />
          </div>
          <MapView map={gameState?.map} />
          <div className="shrink-0">
            <TeamPanel party={gameState?.party ?? []} />
          </div>
        </div>

        {/* Center: Objectives + Log */}
        <div className="flex-1 flex flex-col gap-2 min-h-0 min-w-0">
          <div className="shrink-0">
            <ObjectivesPanel objectives={gameState?.objectives ?? []} />
          </div>
          <ReasoningPanel
            reasoning={reasoning}
            reasoningHistory={reasoningHistory}
            turn={gameState?.turn ?? 0}
          />
        </div>

        {/* Right: Resources + Milestones */}
        <div className="flex flex-col gap-2 w-[280px] shrink-0 min-h-0">
          <div className="shrink-0">
            <InventoryPanel bag={gameState?.bag ?? []} money={gameState?.player.money ?? 0} />
          </div>
          <div className="flex-1 min-h-0 flex flex-col">
            <MilestonesPanel milestones={gameState?.milestones ?? []} />
          </div>
        </div>
      </div>
    </Layout>
  );
}
