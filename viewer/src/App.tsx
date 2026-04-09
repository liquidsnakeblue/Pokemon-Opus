import { useWebSocket } from '@/hooks/useWebSocket';
import { Layout } from '@/components/Layout';
import { GameScreen } from '@/components/GameScreen';
import { ReasoningPanel } from '@/components/ReasoningPanel';
import { TeamPanel } from '@/components/TeamPanel';
import { ObjectivesPanel } from '@/components/ObjectivesPanel';
import { InventoryPanel } from '@/components/InventoryPanel';
import { BadgeTimeline } from '@/components/BadgeTimeline';
import { StatsBar } from '@/components/StatsBar';
import { MilestonesPanel } from '@/components/MilestonesPanel';

export default function App() {
  const { connected, viewers, gameState, screenshot, reasoning, events } =
    useWebSocket();

  return (
    <Layout>
      {/* Top bar: stats + badges */}
      <div className="col-span-full flex flex-col gap-2 px-2 pt-2">
        <StatsBar
          connected={connected}
          viewers={viewers}
          turn={gameState?.turn ?? 0}
          mode={gameState?.mode ?? 'explore'}
          runtime={gameState?.performance.runtime ?? '0:00:00'}
          tokens={gameState?.performance.total_tokens ?? 0}
          cost={gameState?.performance.total_cost_usd ?? 0}
          mapName={gameState?.player.map_name ?? '—'}
        />
        <BadgeTimeline
          badges={gameState?.player.badges ?? []}
          milestones={gameState?.milestones ?? []}
        />
      </div>

      {/* Main 3-column layout */}
      {/* Left: Reasoning */}
      <div className="min-h-0 overflow-hidden">
        <ReasoningPanel reasoning={reasoning} turn={gameState?.turn ?? 0} />
      </div>

      {/* Center: Game screen */}
      <div className="min-h-0 overflow-hidden flex flex-col gap-2">
        <GameScreen screenshot={screenshot} mode={gameState?.mode ?? 'explore'} />
        <TeamPanel party={gameState?.party ?? []} />
      </div>

      {/* Right: Objectives + Inventory + Milestones */}
      <div className="min-h-0 overflow-hidden flex flex-col gap-2">
        <ObjectivesPanel objectives={gameState?.objectives ?? []} />
        <InventoryPanel bag={gameState?.bag ?? []} money={gameState?.player.money ?? 0} />
        <MilestonesPanel milestones={gameState?.milestones ?? []} />
      </div>
    </Layout>
  );
}
