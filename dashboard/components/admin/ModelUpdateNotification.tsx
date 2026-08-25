"use client";

import { X, CheckCircle2 } from "lucide-react";

interface ModelUpdateNotificationProps {
  isOpen: boolean;
  onClose: () => void;
  modelVersion?: string;
}

export default function ModelUpdateNotification({
  isOpen,
  onClose,
  modelVersion = "V2.3",
}: ModelUpdateNotificationProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed top-9 right-6 z-50">
      <div className="bg-[#1c1c1c] border border-[#00b05e] rounded-lg shadow-2xl p-4 min-w-[320px]">
        <div className="flex items-start gap-3">
          <div className="w-6 h-6 bg-[#00b05e] rounded-full flex items-center justify-center flex-shrink-0 mt-0.5">
            <CheckCircle2 className="w-4 h-4 text-black" />
          </div>
          <div className="flex-1">
            <h4 className="text-white text-base font-medium mb-1">
              Model Updated
            </h4>
            <p className="text-[#a8a8a8] text-sm">
              Model {modelVersion} updated successfully.
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-[#a8a8a8] hover:text-white transition-colors flex-shrink-0"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
      </div>
    </div>
  );
}
