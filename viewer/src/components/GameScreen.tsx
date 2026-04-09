interface GameScreenProps {
  mode: string;
}

const STREAM_URL = `http://${window.location.hostname}:3000/stream`;

// 160x144 native, 4x upscale = 640x576
const GAME_WIDTH = 640;
const GAME_HEIGHT = 576;

export function GameScreen({ mode }: GameScreenProps) {
  return (
    <div className="panel flex flex-col shrink-0">
      <div className="panel-header">
        <span>Game</span>
        <span className="ml-auto text-[10px] text-text-tertiary uppercase">{mode}</span>
      </div>
      <div className="bg-black flex items-center justify-center">
        <img
          src={STREAM_URL}
          alt="Game Screen"
          width={GAME_WIDTH}
          height={GAME_HEIGHT}
          style={{ imageRendering: 'pixelated' }}
        />
      </div>
    </div>
  );
}
