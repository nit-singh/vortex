"use client";

interface AssetAllocation {
  name: string;
  percentage: number;
  color: string;
}

interface AssetAllocationCardProps {
  allocations?: AssetAllocation[];
  riskProfile?: string;
}

const defaultAllocations: AssetAllocation[] = [
  { name: "Equity", percentage: 62, color: "#00b05e" },
  { name: "Debt", percentage: 25, color: "deepskyblue" },
  { name: "Cash", percentage: 8, color: "gold" },
  { name: "Alternatives", percentage: 5, color: "#ff6b6b" },
];

export default function AssetAllocationCard({
  allocations = defaultAllocations,
  riskProfile = "Moderate",
}: AssetAllocationCardProps) {
  return (
    <div className="bg-gradient-to-b from-[#2a2a2a] to-[#1c1c1c] rounded-lg shadow-lg p-[1px]">
      <div className="bg-[#161616] rounded-lg">
        <div className="border-b border-[#1c1c1c] p-4">
          <h3 className="text-white font-medium text-sm mb-1">Asset Allocation</h3>
          <p className="text-[#666666] text-[9px]">Portfolio distribution</p>
        </div>
        <div className="p-4">
          <div className="flex items-center justify-between mb-4">
            {/* Placeholder for pie chart - would use recharts or similar */}
            <div className="w-[93px] h-[93px] rounded-full bg-[#1a1a1a] flex items-center justify-center">
              <div className="text-[#666666] text-xs">Chart</div>
            </div>
            <div className="flex-1 ml-4 space-y-2">
              {allocations.map((asset, idx) => (
                <div key={idx} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div
                      className="w-2 h-2 rounded-full"
                      style={{ backgroundColor: asset.color }}
                    />
                    <span className="text-[#cccccc] text-[9px]">{asset.name}</span>
                  </div>
                  <span className="text-white text-[9px]">{asset.percentage}%</span>
                </div>
              ))}
            </div>
          </div>
          <div className="border-t border-[#1c1c1c] pt-2">
            <p className="text-[#666666] text-[8px]">
              Balanced allocation for {riskProfile} risk profile.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

