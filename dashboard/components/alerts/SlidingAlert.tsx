"use client";

import { useEffect, useState } from "react";
import { X, AlertCircle, CheckCircle, Info, AlertTriangle } from "lucide-react";

interface Alert {
  _id: string;
  title: string;
  message: string;
  severity: "info" | "minor" | "major" | "critical";
  created_at: string;
}

interface SlidingAlertProps {
  alert: Alert | null;
  onClose: () => void;
  onMarkAsRead?: (alertId: string) => void;
}

const getSeverityIcon = (severity: string) => {
  switch (severity) {
    case "critical":
      return <AlertCircle className="w-5 h-5 text-[#fb2c36]" />;
    case "major":
      return <AlertTriangle className="w-5 h-5 text-[#f0b100]" />;
    case "minor":
      return <Info className="w-5 h-5 text-[#00b05e]" />;
    default:
      return <Info className="w-5 h-5 text-[#999999]" />;
  }
};

const getSeverityColor = (severity: string) => {
  switch (severity) {
    case "critical":
      return "border-l-[#fb2c36] bg-[rgba(251,44,54,0.1)]";
    case "major":
      return "border-l-[#f0b100] bg-[rgba(240,177,0,0.1)]";
    case "minor":
      return "border-l-[#00b05e] bg-[rgba(0,176,94,0.1)]";
    default:
      return "border-l-[#999999] bg-[rgba(153,153,153,0.1)]";
  }
};

export default function SlidingAlert({
  alert,
  onClose,
  onMarkAsRead,
}: SlidingAlertProps) {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    if (alert) {
      setIsVisible(true);
      // Auto-close after 5 seconds
      const timer = setTimeout(() => {
        handleClose();
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [alert]);

  const handleClose = () => {
    setIsVisible(false);
    setTimeout(() => {
      if (alert && onMarkAsRead) {
        onMarkAsRead(alert._id);
      }
      onClose();
    }, 300); // Wait for animation to complete
  };

  if (!alert) return null;

  return (
    <div
      className={`fixed top-4 right-4 z-50 transition-all duration-300 ${
        isVisible ? "translate-x-0 opacity-100" : "translate-x-full opacity-0"
      }`}
    >
      <div
        className={`min-w-[320px] max-w-[400px] rounded-lg border-l-4 ${getSeverityColor(
          alert.severity
        )} bg-[#1a1a1a] border-[#2a2a2a] shadow-lg`}
      >
        <div className="p-4 flex items-start gap-3">
          <div className="flex-shrink-0 mt-0.5">
            {getSeverityIcon(alert.severity)}
          </div>
          <div className="flex-1 min-w-0">
            <h4 className="text-white font-medium text-sm mb-1">
              {alert.title}
            </h4>
            <p className="text-[#999999] text-xs leading-relaxed">
              {alert.message}
            </p>
            <p className="text-[#666666] text-[10px] mt-2">
              {new Date(alert.created_at).toLocaleString()}
            </p>
          </div>
          <button
            onClick={handleClose}
            className="flex-shrink-0 w-6 h-6 rounded hover:bg-[#2a2a2a] flex items-center justify-center transition-colors"
          >
            <X className="w-4 h-4 text-[#999999]" />
          </button>
        </div>
      </div>
    </div>
  );
}
