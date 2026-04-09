interface GameScreenProps {
  screenshot: string;
  mode: string;
}

export function GameScreen({ screenshot, mode }: GameScreenProps) {
  return (
    <div className="panel flex-1 flex flex-col">
      <div className="panel-header">
        <span>Game</span>
        <span className="ml-auto text-[10px] text-text-tertiary uppercase">{mode}</span>
      </div>
      <div className="flex-1 flex items-center justify-center bg-black p-1">
        {screenshot ? (
          <img
            src={`data:image/png;base64,${screenshot}`}
            alt="Game Screen"
            className="max-w-full max-h-full"
            style={{ imageRendering: 'pixelated' }}
          />
        ) : (
          <div className="text-text-tertiary text-sm font-mono">
            Waiting for game...
          </div>
        )}
      </div>
    </div>
  );
}
