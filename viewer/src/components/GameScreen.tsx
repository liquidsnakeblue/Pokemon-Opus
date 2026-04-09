interface GameScreenProps {
  mode: string;
}

const STREAM_URL = `http://${window.location.hostname}:3000/stream`;

export function GameScreen({ mode }: GameScreenProps) {
  return (
    <div className="panel flex flex-col shrink-0">
      <div className="bg-black flex items-center justify-center overflow-hidden" style={{ height: 'min(320px, 35vh)' }}>
        <img
          src={STREAM_URL}
          alt="Game Screen"
          className="h-full"
          style={{ imageRendering: 'pixelated', aspectRatio: '160 / 144', objectFit: 'contain' }}
        />
      </div>
    </div>
  );
}
