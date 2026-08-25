"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import AdminSidebar from "@/components/admin/AdminSidebar";
import KYCReviewModal from "@/components/admin/KYCReviewModal";
import ModelUpdateNotification from "@/components/admin/ModelUpdateNotification";
import NotificationDropdown from "@/components/alerts/NotificationDropdown";
import { Settings, User } from "lucide-react";
import { CheckCircle2, Clock, XCircle } from "lucide-react";
import { adminApi, alertsApi } from "@/lib/api";

interface UserRow {
  id: string;
  name: string;
  email: string;
  kycStatus: "Verified" | "Submitted" | "Pending" | "IN REVIEW" | "Rejected";
  validationStatus: "passed" | "failed" | "pending"; // Image/video verification result
  kycApprovalStatus?: "approved" | "pending" | "rejected" | "review"; // Admin approval/rejection
  documents: {
    aadhaar: boolean;
    pan: boolean;
    itr: boolean;
    video: boolean;
  };
}

export default function AdminDashboard() {
  const router = useRouter();
  const [userName, setUserName] = useState("Admin");
  const [userId, setUserId] = useState<string>("");
  const [users, setUsers] = useState<UserRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedUser, setSelectedUser] = useState<UserRow | null>(null);
  const [selectedUserDetails, setSelectedUserDetails] = useState<any>(null);
  const [showKYCModal, setShowKYCModal] = useState(false);
  const [showModelUpdate, setShowModelUpdate] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const usersPerPage = 10;

  useEffect(() => {
    const name = localStorage.getItem("userName");
    const userType = localStorage.getItem("userType");
    const id = localStorage.getItem("userId");
    if (name) setUserName(name);
    if (id) setUserId(id);

    if (userType !== "admin") {
      router.push("/login");
    }
  }, [router]);

  // Fetch users from API
  useEffect(() => {
    const fetchUsers = async () => {
      try {
        setLoading(true);
        const response = await adminApi.getAllUsers();
        if (response.success && response.users) {
          // Transform API response to match UserRow interface
          const transformedUsers: UserRow[] = response.users.map(
            (user: any) => ({
              id: user.id,
              name: user.name,
              email: user.email,
              kycStatus: user.kycStatus as
                | "Verified"
                | "Submitted"
                | "Pending"
                | "IN REVIEW"
                | "Rejected",
              validationStatus: (user.validationStatus || "pending") as
                | "passed"
                | "failed"
                | "pending",
              kycApprovalStatus: user.kycApprovalStatus as
                | "approved"
                | "pending"
                | "rejected"
                | "review"
                | undefined,
              documents: user.documents || {
                aadhaar: false,
                pan: false,
                itr: false,
                video: false,
              },
            })
          );
          setUsers(transformedUsers);
        }
      } catch (error) {
        console.error("Failed to fetch users:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchUsers();
  }, []);

  const getKYCStatusBadge = (status: string) => {
    const statusLower = status.toLowerCase();
    if (statusLower === "review") {
      return (
        <span className="bg-[#3d2e00] border border-[#5c4500] text-[#ffb800] text-xs px-2 py-1 rounded-full">
          REVIEW
        </span>
      );
    }
    switch (status.toLowerCase()) {
      case "verified":
        return (
          <span className="bg-[#003d1f] border border-[#005a2e] text-[#00b05e] text-xs px-2 py-1 rounded-full">
            Verified
          </span>
        );
      case "submitted":
        return (
          <span className="bg-[#002b4d] border border-[#003d6b] text-[#4c82ff] text-xs px-2 py-1 rounded-full">
            Submitted
          </span>
        );
      case "pending":
        return (
          <span className="bg-[#3d2e00] border border-[#5c4500] text-[#ffb800] text-xs px-2 py-1 rounded-full">
            Pending
          </span>
        );
      default:
        return null;
    }
  };

  const getValidationStatusBadge = (status: string) => {
    switch (status?.toLowerCase()) {
      case "passed":
        return (
          <div className="flex items-center gap-1.5">
            <CheckCircle2 className="w-3.5 h-3.5 text-[#00b05e]" />
            <span className="text-[#00b05e] text-xs font-medium">PASSED</span>
          </div>
        );
      case "failed":
        return (
          <div className="flex items-center gap-1.5">
            <XCircle className="w-3.5 h-3.5 text-[#ff4c4c]" />
            <span className="text-[#ff4c4c] text-xs font-medium">FAILED</span>
          </div>
        );
      case "pending":
        return (
          <div className="flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5 text-[#999999]" />
            <span className="text-[#999999] text-xs">PENDING</span>
          </div>
        );
      default:
        return (
          <div className="flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5 text-[#999999]" />
            <span className="text-[#999999] text-xs">PENDING</span>
          </div>
        );
    }
  };

  const handleViewDetails = async (user: UserRow) => {
    try {
      setSelectedUser(user);
      // Fetch full user details
      const response = await adminApi.getUserDetails(user.id);
      if (response.success && response.user) {
        setSelectedUserDetails(response.user);
        setShowKYCModal(true);
      }
    } catch (error) {
      console.error("Failed to fetch user details:", error);
      alert("Failed to load user details. Please try again.");
    }
  };

  const handleKYCApproved = () => {
    // Refresh users list
    const fetchUsers = async () => {
      try {
        const response = await adminApi.getAllUsers();
        if (response.success && response.users) {
          const transformedUsers: UserRow[] = response.users.map(
            (user: any) => ({
              id: user.id,
              name: user.name,
              email: user.email,
              kycStatus: user.kycStatus as
                | "Verified"
                | "Submitted"
                | "Pending"
                | "IN REVIEW"
                | "Rejected",
              validationStatus: (user.validationStatus || "pending") as
                | "passed"
                | "failed"
                | "pending",
              kycApprovalStatus: user.kycApprovalStatus as
                | "approved"
                | "pending"
                | "rejected"
                | "review"
                | undefined,
              documents: user.documents || {
                aadhaar: false,
                pan: false,
                itr: false,
                video: false,
              },
            })
          );
          setUsers(transformedUsers);
        }
      } catch (error) {
        console.error("Failed to refresh users:", error);
      }
    };
    fetchUsers();
    setShowKYCModal(false);
    setSelectedUser(null);
    setSelectedUserDetails(null);
  };

  const handleKYCRejected = () => {
    // Refresh users list
    const fetchUsers = async () => {
      try {
        const response = await adminApi.getAllUsers();
        if (response.success && response.users) {
          const transformedUsers: UserRow[] = response.users.map(
            (user: any) => ({
              id: user.id,
              name: user.name,
              email: user.email,
              kycStatus: user.kycStatus as
                | "Verified"
                | "Submitted"
                | "Pending"
                | "IN REVIEW"
                | "Rejected",
              validationStatus: (user.validationStatus || "pending") as
                | "passed"
                | "failed"
                | "pending",
              kycApprovalStatus: user.kycApprovalStatus as
                | "approved"
                | "pending"
                | "rejected"
                | "review"
                | undefined,
              documents: user.documents || {
                aadhaar: false,
                pan: false,
                itr: false,
                video: false,
              },
            })
          );
          setUsers(transformedUsers);
        }
      } catch (error) {
        console.error("Failed to refresh users:", error);
      }
    };
    fetchUsers();
    setShowKYCModal(false);
    setSelectedUser(null);
    setSelectedUserDetails(null);
  };

  const handleUpdateModel = () => {
    setShowModelUpdate(true);
    setTimeout(() => setShowModelUpdate(false), 5000);
  };

  const totalPages = Math.ceil(users.length / usersPerPage);
  const startIndex = (currentPage - 1) * usersPerPage;
  const endIndex = startIndex + usersPerPage;
  const displayedUsers = users.slice(startIndex, endIndex);

  const getInitials = (name: string) => {
    const parts = name.split(" ");
    if (parts.length >= 2) {
      return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }
    return name.substring(0, 2).toUpperCase();
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-[#0d0d0d] to-[#121212]">
      <AdminSidebar userName={userName} />
      <div className="ml-64">
        {/* Header */}
        <div className="bg-[#111111] border-b border-[#2a2a2a] px-6 py-4">
          <div className="flex items-center justify-between">
            <h1 className="text-white font-medium text-lg">Company Portal</h1>
            <div className="flex items-center gap-3">
              {userId && (
                <NotificationDropdown
                  userId={userId}
                  onMarkAsRead={async (alertId: string) => {
                    try {
                      await alertsApi.markAsRead(alertId);
                    } catch (error) {
                      console.error("Failed to mark alert as read:", error);
                    }
                  }}
                />
              )}
              <button className="w-9 h-9 rounded-lg hover:bg-[#1a1a1a] flex items-center justify-center transition-colors">
                <Settings className="w-[18px] h-[18px] text-[#999999]" />
              </button>
              <button className="w-9 h-9 rounded-lg hover:bg-[#1a1a1a] flex items-center justify-center transition-colors">
                <User className="w-[18px] h-[18px] text-[#999999]" />
              </button>
            </div>
          </div>
        </div>

        {/* Main Content */}
        <div className="p-4">
          {/* Page Header */}
          <div className="flex items-start justify-between mb-5">
            <div>
              <h2 className="text-white text-2xl font-medium mb-1.5">
                Admin Dashboard
              </h2>
              <p className="text-[#a8a8a8] text-[10px]">
                Manage users, KYC status, and model configurations.
              </p>
            </div>
          </div>

          {/* User Management Table */}
          <div className="bg-[#1c1c1c] border border-[#2a2a2a] rounded-lg overflow-hidden">
            {/* Table Header */}
            <div className="border-b border-[#2a2a2a] px-4 py-2.5">
              <h3 className="text-white text-xs font-medium mb-0.5">
                User Management
              </h3>
              <p className="text-[#a8a8a8] text-[10px]">
                Review and manage user KYC submissions
              </p>
            </div>

            {/* Table */}
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-[#2a2a2a]">
                    <th className="text-left px-4 py-2.5 text-[#a8a8a8] text-[10px] font-bold uppercase tracking-wide">
                      Name
                    </th>
                    <th className="text-left px-4 py-2.5 text-[#a8a8a8] text-[10px] font-bold uppercase tracking-wide">
                      KYC Status
                    </th>
                    <th className="text-left px-4 py-2.5 text-[#a8a8a8] text-[10px] font-bold uppercase tracking-wide">
                      Validation Status
                    </th>
                    <th className="text-left px-4 py-2.5 text-[#a8a8a8] text-[10px] font-bold uppercase tracking-wide">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {loading ? (
                    <tr>
                      <td
                        colSpan={4}
                        className="px-4 py-8 text-center text-[#a8a8a8] text-xs"
                      >
                        Loading users...
                      </td>
                    </tr>
                  ) : displayedUsers.length === 0 ? (
                    <tr>
                      <td
                        colSpan={4}
                        className="px-4 py-8 text-center text-[#a8a8a8] text-xs"
                      >
                        No users found
                      </td>
                    </tr>
                  ) : (
                    displayedUsers.map((user) => (
                      <tr
                        key={user.id}
                        className="border-b border-[#2a2a2a] hover:bg-[#1a1a1a] transition-colors"
                      >
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <div className="w-7 h-7 bg-[#2a2a2a] rounded-full flex items-center justify-center flex-shrink-0">
                              <span className="text-[#00b05e] text-xs font-medium">
                                {getInitials(user.name)}
                              </span>
                            </div>
                            <div>
                              <p className="text-white text-xs leading-tight">
                                {user.name}
                              </p>
                              <p className="text-[#a8a8a8] text-[10px] leading-tight">
                                {user.email}
                              </p>
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          {getKYCStatusBadge(user.kycStatus)}
                        </td>
                        <td className="px-4 py-3">
                          {getValidationStatusBadge(user.validationStatus)}
                        </td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => handleViewDetails(user)}
                            className="bg-[#2a2a2a] text-white text-[9px] px-3 py-1.5 rounded-md hover:bg-[#333333] transition-colors"
                          >
                            View Details
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div className="border-t border-[#2a2a2a] px-4 py-2.5 flex items-center justify-between">
              <p className="text-[#a8a8a8] text-[9px]">
                Showing {startIndex + 1} to {Math.min(endIndex, users.length)}{" "}
                of {users.length} users
              </p>
              <div className="flex items-center gap-1.5">
                <button
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  disabled={currentPage === 1}
                  className="bg-[#2a2a2a] text-[#666666] text-[9px] px-3 py-1.5 rounded-md hover:bg-[#333333] disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Previous
                </button>
                {[...Array(totalPages)].map((_, i) => (
                  <button
                    key={i + 1}
                    onClick={() => setCurrentPage(i + 1)}
                    className={`text-[9px] px-2.5 py-1.5 rounded-md ${
                      currentPage === i + 1
                        ? "bg-[#00b05e] text-black"
                        : "bg-[#2a2a2a] text-white hover:bg-[#333333]"
                    }`}
                  >
                    {i + 1}
                  </button>
                ))}
                <button
                  onClick={() =>
                    setCurrentPage((p) => Math.min(totalPages, p + 1))
                  }
                  disabled={currentPage === totalPages}
                  className="bg-[#2a2a2a] text-white text-[9px] px-3 py-1.5 rounded-md hover:bg-[#333333] disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Next
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* KYC Review Modal */}
      {selectedUser && selectedUserDetails && (
        <KYCReviewModal
          isOpen={showKYCModal}
          onClose={() => {
            setShowKYCModal(false);
            setSelectedUser(null);
            setSelectedUserDetails(null);
          }}
          userId={selectedUser.id}
          user={selectedUserDetails}
          onApprove={handleKYCApproved}
          onReject={handleKYCRejected}
        />
      )}

      {/* Model Update Notification */}
      <ModelUpdateNotification
        isOpen={showModelUpdate}
        onClose={() => setShowModelUpdate(false)}
      />
    </div>
  );
}
