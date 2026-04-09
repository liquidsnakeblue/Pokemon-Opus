import type { BagItem } from '@/lib/types';

interface InventoryPanelProps {
  bag: BagItem[];
  money: number;
}

export function InventoryPanel({ bag, money }: InventoryPanelProps) {
  return (
    <div className="panel flex-1 min-h-0 flex flex-col">
      <div className="panel-header">
        <span>Inventory</span>
        <span className="ml-auto text-[10px] text-type-electric font-mono">
          ¥{money.toLocaleString()}
        </span>
      </div>
      <div className="panel-body flex-1 overflow-y-auto">
        {bag.length === 0 ? (
          <div className="text-text-tertiary text-xs italic">Empty bag</div>
        ) : (
          <div className="space-y-1">
            {bag.map((item, i) => (
              <div
                key={`${item.item}-${i}`}
                className="flex items-center justify-between text-xs"
              >
                <span className="text-text-primary truncate">{item.item}</span>
                <span className="text-text-tertiary font-mono ml-2 shrink-0">
                  x{item.quantity}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
