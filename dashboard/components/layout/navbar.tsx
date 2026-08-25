"use client";

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { LogOut, User, Settings } from "lucide-react";

export default function Navbar() {
  const router = useRouter();
  const pathname = usePathname();

  const handleLogout = () => {
    localStorage.removeItem("isAuthenticated");
    localStorage.removeItem("userType");
    localStorage.removeItem("userEmail");
    router.push("/login");
  };

  const isCompany = pathname?.startsWith("/company");
  const isConsumer = pathname?.startsWith("/consumer");

  return (
    <nav className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-14 items-center">
        <div className="mr-4 flex">
          <Link
            href={isCompany ? "/company/dashboard" : "/consumer/dashboard"}
            className="mr-6 flex items-center space-x-2"
          >
            <span className="font-bold">Pathway</span>
          </Link>
        </div>
        <div className="flex flex-1 items-center justify-between space-x-2">
          <div className="flex items-center space-x-6 text-sm font-medium">
            {isConsumer && (
              <>
                <Link
                  href="/consumer/dashboard"
                  className={`transition-colors hover:text-foreground/80 ${
                    pathname === "/consumer/dashboard"
                      ? "text-foreground"
                      : "text-foreground/60"
                  }`}
                >
                  Dashboard
                </Link>
                <Link
                  href="/consumer/onboarding"
                  className={`transition-colors hover:text-foreground/80 ${
                    pathname === "/consumer/onboarding"
                      ? "text-foreground"
                      : "text-foreground/60"
                  }`}
                >
                  Onboarding
                </Link>
              </>
            )}
            {isCompany && (
              <>
                <Link
                  href="/company/dashboard"
                  className={`transition-colors hover:text-foreground/80 ${
                    pathname === "/company/dashboard"
                      ? "text-foreground"
                      : "text-foreground/60"
                  }`}
                >
                  Dashboard
                </Link>
                <Link
                  href="/company/reviews"
                  className={`transition-colors hover:text-foreground/80 ${
                    pathname?.startsWith("/company/reviews")
                      ? "text-foreground"
                      : "text-foreground/60"
                  }`}
                >
                  Reviews
                </Link>
                <Link
                  href="/company/settings"
                  className={`transition-colors hover:text-foreground/80 ${
                    pathname === "/company/settings"
                      ? "text-foreground"
                      : "text-foreground/60"
                  }`}
                >
                  Settings
                </Link>
              </>
            )}
          </div>
          <div className="flex items-center space-x-2">
            <button
              onClick={handleLogout}
              className="inline-flex items-center justify-center rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 h-10 px-4 py-2 hover:bg-accent hover:text-accent-foreground"
            >
              <LogOut className="h-4 w-4 mr-2" />
              Logout
            </button>
          </div>
        </div>
      </div>
    </nav>
  );
}
