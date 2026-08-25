"use client";

import { usePathname, useRouter } from "next/navigation";
import { LayoutDashboard, User, LogOut } from "lucide-react";
import { cn } from "@/lib/utils";

interface AdminSidebarProps {
  userName?: string;
}

export default function AdminSidebar({
  userName = "Admin",
}: AdminSidebarProps) {
  const pathname = usePathname();
  const router = useRouter();

  const navItems = [
    { icon: LayoutDashboard, label: "Dashboard", path: "/admin/dashboard" },
  ];

  const handleLogout = () => {
    localStorage.removeItem("isAuthenticated");
    localStorage.removeItem("userType");
    localStorage.removeItem("userEmail");
    localStorage.removeItem("userId");
    localStorage.removeItem("userName");
    router.push("/login");
  };

  return (
    <div className="fixed left-0 top-0 h-screen w-64 bg-[#0d0d0d] border-r border-[#1a1a1a] flex flex-col justify-between">
      {/* Logo and Brand */}
      <div className="p-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 bg-[#00b05e] rounded-lg flex items-center justify-center">
            <span className="text-white font-bold text-lg">I</span>
          </div>
          <div>
            <h2 className="text-white font-semibold text-base">InvestPro</h2>
            <p className="text-[#666666] text-xs">Dashboard</p>
          </div>
        </div>

        {/* Navigation */}
        <nav className="space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = pathname === item.path;

            return (
              <button
                key={item.path}
                onClick={() => router.push(item.path)}
                className={cn(
                  "w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-colors",
                  isActive
                    ? "bg-[rgba(0,176,94,0.1)] text-[#00b05e]"
                    : "text-[#999999] hover:bg-[#1a1a1a]"
                )}
              >
                <Icon className="w-[18px] h-[18px]" />
                <span className="text-sm">{item.label}</span>
              </button>
            );
          })}
        </nav>
      </div>

      {/* User Profile */}
      <div className="p-4 border-t border-[#1a1a1a]">
        <div className="flex items-center gap-3 mb-3">
          <div className="w-10 h-10 bg-[#161616] rounded-full flex items-center justify-center">
            <User className="w-[18px] h-[18px] text-[#999999]" />
          </div>
          <div className="flex-1">
            <p className="text-white text-sm">{userName}</p>
            <p className="text-[#666666] text-xs">Premium</p>
          </div>
        </div>
        <button
          onClick={handleLogout}
          className="w-full flex items-center gap-2 px-4 py-2 rounded-lg text-[#999999] hover:bg-[#1a1a1a] transition-colors"
        >
          <LogOut className="w-4 h-4" />
          <span className="text-sm">Logout</span>
        </button>
      </div>
    </div>
  );
}
