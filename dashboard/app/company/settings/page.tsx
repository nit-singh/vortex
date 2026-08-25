"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Navbar from "@/components/layout/navbar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Save } from "lucide-react";

export default function SettingsPage() {
  const router = useRouter();
  const [settings, setSettings] = useState({
    companyName: "",
    email: "",
    apiKey: "",
    webhookUrl: "",
  });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const isAuthenticated = localStorage.getItem("isAuthenticated");
    if (!isAuthenticated) {
      router.push("/login");
      return;
    }

    const userType = localStorage.getItem("userType");
    if (userType !== "company") {
      router.push("/consumer/dashboard");
      return;
    }

    // Load settings from localStorage or API
    const savedSettings = localStorage.getItem("companySettings");
    if (savedSettings) {
      setSettings(JSON.parse(savedSettings));
    } else {
      const email = localStorage.getItem("userEmail");
      if (email) {
        setSettings((prev) => ({ ...prev, email }));
      }
    }
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    // Simulate API call
    setTimeout(() => {
      localStorage.setItem("companySettings", JSON.stringify(settings));
      setLoading(false);
      alert("Settings saved successfully!");
    }, 1000);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#0d0d0d] to-[#121212]">
      <Navbar />
      <div className="container mx-auto p-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-white mb-2">Settings</h1>
          <p className="text-gray-400">
            Manage your company settings and preferences
          </p>
        </div>

        <Card className="bg-[#1a1a1a] border-[#2a2a2a]">
          <CardHeader>
            <CardTitle className="text-white">Company Information</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-6">
              <div>
                <Label htmlFor="companyName" className="text-gray-400">
                  Company Name
                </Label>
                <Input
                  id="companyName"
                  value={settings.companyName}
                  onChange={(e) =>
                    setSettings({ ...settings, companyName: e.target.value })
                  }
                  className="mt-2 bg-[#0d0d0d] border-[#2a2a2a] text-white"
                  placeholder="Enter company name"
                />
              </div>

              <div>
                <Label htmlFor="email" className="text-gray-400">
                  Email
                </Label>
                <Input
                  id="email"
                  type="email"
                  value={settings.email}
                  onChange={(e) =>
                    setSettings({ ...settings, email: e.target.value })
                  }
                  className="mt-2 bg-[#0d0d0d] border-[#2a2a2a] text-white"
                  placeholder="Enter email"
                />
              </div>

              <div>
                <Label htmlFor="apiKey" className="text-gray-400">
                  API Key
                </Label>
                <Input
                  id="apiKey"
                  type="password"
                  value={settings.apiKey}
                  onChange={(e) =>
                    setSettings({ ...settings, apiKey: e.target.value })
                  }
                  className="mt-2 bg-[#0d0d0d] border-[#2a2a2a] text-white"
                  placeholder="Enter API key"
                />
              </div>

              <div>
                <Label htmlFor="webhookUrl" className="text-gray-400">
                  Webhook URL
                </Label>
                <Input
                  id="webhookUrl"
                  type="url"
                  value={settings.webhookUrl}
                  onChange={(e) =>
                    setSettings({ ...settings, webhookUrl: e.target.value })
                  }
                  className="mt-2 bg-[#0d0d0d] border-[#2a2a2a] text-white"
                  placeholder="https://example.com/webhook"
                />
              </div>

              <Button
                type="submit"
                disabled={loading}
                className="bg-[#00b05e] text-black hover:bg-[#00a055]"
              >
                <Save className="h-4 w-4 mr-2" />
                {loading ? "Saving..." : "Save Settings"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
