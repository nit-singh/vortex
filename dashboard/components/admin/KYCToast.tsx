"use client";

import { X, Bell } from "lucide-react";
import { useState } from "react";

interface KYCToastProps {
  userName: string;
  onReview: () => void;
  onClose: () => void;
}

export default function KYCToast({
  userName,
  onReview,
  onClose,
}: KYCToastProps) {
  return (
    <div className="fixed top-6 right-6 z-50 flex items-start gap-0">
      {/* Gradient Border */}
      <div className="w-2.5 h-full bg-gradient-to-b from-[#a855f7] to-[#4c82ff] rounded-l-xl" />

      {/* Toast Content */}
      <div className="bg-[#343434] border border-[#2a2a2a] rounded-r-xl shadow-2xl p-4 min-w-[641px]">
        <div className="flex items-start gap-4">
          {/* Icon */}
          <div className="relative flex-shrink-0">
            <div className="w-12 h-12 bg-[#2a2a2a] rounded-lg flex items-center justify-center">
              <Bell className="w-6 h-6 text-[#4c82ff]" />
            </div>
            <div className="absolute -top-1 -right-1 w-4 h-4 bg-[#4c82ff] border-2 border-[#1e1e1e] rounded-full flex items-center justify-center">
              <div className="w-2 h-2 bg-white rounded-full" />
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 min-w-0">
            <h4 className="text-white text-base font-medium mb-1">
              New KYC Submission
            </h4>
            <p className="text-[#b5b5b5] text-sm mb-1">
              {userName} has just submitted verification documents.
            </p>
            <p className="text-[#666666] text-xs">Just now</p>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-3 flex-shrink-0">
            <button
              onClick={onReview}
              className="bg-[#00f076] text-black text-sm font-medium px-4 py-2 rounded-lg hover:bg-[#00d66a] transition-colors shadow-lg whitespace-nowrap"
            >
              Review Now
            </button>
            <button
              onClick={onClose}
              className="text-[#a8a8a8] hover:text-white transition-colors flex-shrink-0"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
