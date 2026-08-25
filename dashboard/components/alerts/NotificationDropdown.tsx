"use client";

import { useEffect, useRef, useState } from "react";
import {
  Bell,
  X,
  AlertCircle,
  Info,
  AlertTriangle,
  CheckCircle,
} from "lucide-react";

interface Alert {
  _id: string;
  title: string;
  message: string;
  severity: "info" | "minor" | "major" | "critical";
  read: boolean;
  created_at: string;
}

interface NotificationDropdownProps {
  userId: string;
  onMarkAsRead: (alertId: string) => Promise<void>;
}

const getSeverityIcon = (severity: string) => {
  switch (severity) {
    case "critical":
      return <AlertCircle className="w-4 h-4 text-[#fb2c36]" />;
    case "major":
      return <AlertTriangle className="w-4 h-4 text-[#f0b100]" />;
    case "minor":
      return <Info className="w-4 h-4 text-[#00b05e]" />;
    default:
      return <Info className="w-4 h-4 text-[#999999]" />;
  }
};

const getSeverityColor = (severity: string) => {
  switch (severity) {
    case "critical":
      return "border-l-[#fb2c36]";
    case "major":
      return "border-l-[#f0b100]";
    case "minor":
      return "border-l-[#00b05e]";
    default:
      return "border-l-[#999999]";
  }
};

export default function NotificationDropdown({
  userId,
  onMarkAsRead,
}: NotificationDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isOpen) {
      fetchAlerts();
    }
  }, [isOpen, userId]);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen]);

  // Poll for unread count
  useEffect(() => {
    const pollUnreadCount = async () => {
      try {
        const API_BASE_URL =
          process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
        const response = await fetch(
          `${API_BASE_URL}/api/v1/user/${userId}/alerts/unread/count`
        );
        if (response.ok) {
          const data = await response.json();
          setUnreadCount(data.unread_count || 0);
        }
      } catch (error) {
        console.error("Failed to fetch unread count:", error);
      }
    };

    pollUnreadCount();
    const interval = setInterval(pollUnreadCount, 10000); // Poll every 10 seconds
    return () => clearInterval(interval);
  }, [userId]);

  const fetchAlerts = async () => {
    setLoading(true);
    try {
      const API_BASE_URL =
        process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
      const response = await fetch(
        `${API_BASE_URL}/api/v1/user/${userId}/alerts?limit=20`
      );
      if (response.ok) {
        const data = await response.json();
        setAlerts(data.alerts || []);
        setUnreadCount(data.unread_count || 0);
      }
    } catch (error) {
      console.error("Failed to fetch alerts:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleMarkAsRead = async (alertId: string) => {
    try {
      await onMarkAsRead(alertId);
      // Update local state
      setAlerts((prev) =>
        prev.map((alert) =>
          alert._id === alertId ? { ...alert, read: true } : alert
        )
      );
      setUnreadCount((prev) => Math.max(0, prev - 1));
    } catch (error) {
      console.error("Failed to mark alert as read:", error);
    }
  };

  const unreadAlerts = alerts.filter((a) => !a.read);
  const readAlerts = alerts.filter((a) => a.read);

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-9 h-9 rounded-lg hover:bg-[#1a1a1a] flex items-center justify-center transition-colors relative"
      >
        <Bell className="w-[18px] h-[18px] text-[#999999]" />
        {unreadCount > 0 && (
          <span className="absolute top-1 right-1 w-2 h-2 bg-[#fb2c36] rounded-full border border-[#0d0d0d]"></span>
        )}
      </button>

      {isOpen && (
        <div className="absolute right-0 top-12 w-96 bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg shadow-xl z-50 max-h-[600px] flex flex-col">
          {/* Header */}
          <div className="p-4 border-b border-[#2a2a2a] flex items-center justify-between">
            <h3 className="text-white font-medium text-sm">Notifications</h3>
            <button
              onClick={() => setIsOpen(false)}
              className="w-6 h-6 rounded hover:bg-[#2a2a2a] flex items-center justify-center transition-colors"
            >
              <X className="w-4 h-4 text-[#999999]" />
            </button>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <div className="p-8 text-center text-[#999999] text-sm">
                Loading...
              </div>
            ) : alerts.length === 0 ? (
              <div className="p-8 text-center text-[#999999] text-sm">
                No notifications
              </div>
            ) : (
              <>
                {unreadAlerts.length > 0 && (
                  <div className="p-2">
                    <div className="px-2 py-1 text-[#666666] text-[10px] font-medium uppercase">
                      Unread ({unreadAlerts.length})
                    </div>
                    {unreadAlerts.map((alert) => (
                      <div
                        key={alert._id}
                        className={`p-3 border-l-4 ${getSeverityColor(
                          alert.severity
                        )} bg-[#161616] hover:bg-[#1a1a1a] cursor-pointer transition-colors`}
                        onClick={() => handleMarkAsRead(alert._id)}
                      >
                        <div className="flex items-start gap-2">
                          <div className="flex-shrink-0 mt-0.5">
                            {getSeverityIcon(alert.severity)}
                          </div>
                          <div className="flex-1 min-w-0">
                            <h4 className="text-white font-medium text-xs mb-1">
                              {alert.title}
                            </h4>
                            <p className="text-[#999999] text-[10px] leading-relaxed line-clamp-2">
                              {alert.message}
                            </p>
                            <p className="text-[#666666] text-[9px] mt-1">
                              {new Date(alert.created_at).toLocaleString()}
                            </p>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {readAlerts.length > 0 && (
                  <div className="p-2 border-t border-[#2a2a2a]">
                    <div className="px-2 py-1 text-[#666666] text-[10px] font-medium uppercase">
                      Read ({readAlerts.length})
                    </div>
                    {readAlerts.map((alert) => (
                      <div
                        key={alert._id}
                        className={`p-3 border-l-4 ${getSeverityColor(
                          alert.severity
                        )} bg-[#161616] opacity-60`}
                      >
                        <div className="flex items-start gap-2">
                          <div className="flex-shrink-0 mt-0.5">
                            {getSeverityIcon(alert.severity)}
                          </div>
                          <div className="flex-1 min-w-0">
                            <h4 className="text-white font-medium text-xs mb-1">
                              {alert.title}
                            </h4>
                            <p className="text-[#999999] text-[10px] leading-relaxed line-clamp-2">
                              {alert.message}
                            </p>
                            <p className="text-[#666666] text-[9px] mt-1">
                              {new Date(alert.created_at).toLocaleString()}
                            </p>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
