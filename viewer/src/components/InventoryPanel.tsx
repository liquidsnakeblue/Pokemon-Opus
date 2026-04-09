import type { BagItem } from '@/lib/types';

interface InventoryPanelProps {
  bag: BagItem[];
  money: number;
}

export function InventoryPanel({ bag, money }: InventoryPanelProps) {
  return (
    <div className="panel flex flex-col">
      <div className="panel-header">
        <span>Resources</span>
      </div>
      <div className="panel-body">
        {bag.length === 0 && money === 0 ? (
          <div className="text-text-tertiary text-xs italic">No items</div>
        ) : (
          <div className="space-y-1 text-xs">
            {bag.map((item, i) => (
              <div key={`${item.item}-${i}`} className="flex items-center justify-between">
                <span className="text-text-primary truncate">{item.item}</span>
                <span className="text-text-tertiary font-mono ml-2 shrink-0">x{item.quantity}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
