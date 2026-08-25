"use client";

import { X, Play, FileText } from "lucide-react";
import { useState } from "react";
import { adminApi } from "@/lib/api";

interface UserData {
  id: string;
  name: string;
  email: string;
  kycStatus: string;
  validationStatus: string;
  dateOfBirth?: string;
  contactNumber?: string;
  address?: string;
  occupation?: string;
  maritalStatus?: string;
  citizenship?: string;
  incomeRange?: string;
  amountToInvest?: string;
  dependents?: number;
  dependentDetails?: string;
  investmentQ1?: string;
  investmentQ2?: string;
  investmentQ3?: string;
  investmentQ4?: string;
  investmentQ5?: string;
  investmentQ6?: string;
  documents?: {
    aadhaar: boolean;
    pan: boolean;
    itr: boolean;
    video: boolean;
  };
  documentUrls?: {
    aadhaar?: string;
    pan?: string;
    itr?: string;
    video?: string;
  };
  videoCloudinaryUrl?: string;
}

interface KYCReviewModalProps {
  isOpen: boolean;
  onClose: () => void;
  userId: string;
  user: UserData;
  onApprove: () => void;
  onReject: () => void;
}

export default function KYCReviewModal({
  isOpen,
  onClose,
  userId,
  user,
  onApprove,
  onReject,
}: KYCReviewModalProps) {
  const [loading, setLoading] = useState(false);
  const [rejectionReason, setRejectionReason] = useState("");

  if (!isOpen) return null;

  const getInitials = (name: string) => {
    const parts = name.split(" ");
    if (parts.length >= 2) {
      return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }
    return name.substring(0, 2).toUpperCase();
  };

  const getKYCStatusBadge = (status: string) => {
    switch (status.toLowerCase()) {
      case "verified":
      case "approved":
        return (
          <span className="bg-[#003d1f] border border-[#005a2e] text-[#00b05e] text-xs px-2 py-1 rounded-full">
            Verified
          </span>
        );
      case "review":
        return (
          <span className="bg-[#3d2e00] border border-[#5c4500] text-[#ffb800] text-xs px-2 py-1 rounded-full">
            REVIEW
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
      case "rejected":
        return (
          <span className="bg-[#3d0000] border border-[#5c0000] text-[#ff4c4c] text-xs px-2 py-1 rounded-full">
            Rejected
          </span>
        );
      default:
        return (
          <span className="bg-[#3d2e00] border border-[#5c4500] text-[#ffb800] text-xs px-2 py-1 rounded-full">
            {status}
          </span>
        );
    }
  };

  const handleApprove = async () => {
    try {
      setLoading(true);
      await adminApi.approveKYC(userId);
      onApprove();
    } catch (error: any) {
      console.error("Failed to approve KYC:", error);
      alert(
        error.response?.data?.message ||
          "Failed to approve KYC. Please try again."
      );
    } finally {
      setLoading(false);
    }
  };

  const handleReject = async () => {
    if (!rejectionReason.trim()) {
      alert("Please provide a reason for rejection");
      return;
    }
    try {
      setLoading(true);
      await adminApi.rejectKYC(userId, rejectionReason);
      onReject();
    } catch (error: any) {
      console.error("Failed to reject KYC:", error);
      alert(
        error.response?.data?.message ||
          "Failed to reject KYC. Please try again."
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="fixed inset-0 flex items-center justify-center z-50 p-4">
        <div className="bg-[#1a1a1a] border border-[#2a2a2a] rounded-xl shadow-2xl w-full max-w-[681px] max-h-[90vh] overflow-y-auto">
          {/* Header */}
          <div className="flex items-start justify-between p-6 border-b border-[#2a2a2a]">
            <div>
              <h2 className="text-white text-xl font-medium mb-1">
                KYC Verification – {user.name}
              </h2>
              <p className="text-[#b5b5b5] text-xs">
                Review submitted documents and approve or reject user KYC.
              </p>
            </div>
            <button
              onClick={onClose}
              className="text-[#a8a8a8] hover:text-white transition-colors"
            >
              <X className="w-6 h-6" />
            </button>
          </div>

          {/* Content */}
          <div className="p-6 space-y-6">
            {/* User Info Card */}
            <div className="bg-[#1f1f1f] border border-[#2a2a2a] rounded-lg p-4 flex items-center gap-3">
              <div className="w-12 h-12 bg-[#2a2a2a] rounded-full flex items-center justify-center">
                <span className="text-[#00b05e] text-sm font-medium">
                  {getInitials(user.name)}
                </span>
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <p className="text-white text-sm font-medium">{user.name}</p>
                  {getKYCStatusBadge(user.kycStatus)}
                </div>
                <p className="text-[#b5b5b5] text-xs">{user.email}</p>
              </div>
            </div>

            {/* Documents Section */}
            <div>
              <h3 className="text-white text-sm font-medium mb-3">
                Uploaded Documents
              </h3>
              <div className="grid grid-cols-3 gap-3 mb-3">
                {[
                  { name: "Aadhaar", key: "aadhaar" },
                  { name: "PAN Card", key: "pan" },
                  { name: "ITR Document", key: "itr" },
                ].map((doc) => (
                  <div
                    key={doc.key}
                    className="bg-[#1f1f1f] border border-[#2a2a2a] rounded-lg p-4"
                  >
                    <div className="bg-[#2a2a2a] h-24 rounded-lg flex items-center justify-center mb-3">
                      {user.documents?.[
                        doc.key as keyof typeof user.documents
                      ] ? (
                        <FileText className="w-8 h-8 text-[#00b05e]" />
                      ) : (
                        <FileText className="w-8 h-8 text-[#666666]" />
                      )}
                    </div>
                    <p className="text-white text-base mb-4">{doc.name}</p>
                    {user.documentUrls?.[
                      doc.key as keyof typeof user.documentUrls
                    ] ? (
                      <a
                        href={
                          user.documentUrls[
                            doc.key as keyof typeof user.documentUrls
                          ]
                        }
                        target="_blank"
                        rel="noopener noreferrer"
                        className="w-full bg-[#2a2a2a] border border-[#393939] text-white text-xs py-2 rounded-lg hover:bg-[#333333] transition-colors inline-block text-center"
                      >
                        View Full Document
                      </a>
                    ) : (
                      <button
                        disabled={
                          !user.documents?.[
                            doc.key as keyof typeof user.documents
                          ]
                        }
                        className="w-full bg-[#2a2a2a] border border-[#393939] text-white text-xs py-2 rounded-lg hover:bg-[#333333] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {user.documents?.[
                          doc.key as keyof typeof user.documents
                        ]
                          ? "Document Not Uploaded"
                          : "Not Available"}
                      </button>
                    )}
                  </div>
                ))}
              </div>

              {/* Video Section */}
              {user.videoCloudinaryUrl && (
                <div className="bg-[#1f1f1f] border border-[#2a2a2a] rounded-lg p-4">
                  <div className="flex gap-4">
                    <div className="bg-[#2a2a2a] w-36 h-24 rounded-lg flex items-center justify-center relative">
                      <div className="absolute bg-[#00b05e] w-9 h-9 rounded-full flex items-center justify-center">
                        <Play className="w-4 h-4 text-black ml-0.5" />
                      </div>
                    </div>
                    <div className="flex-1">
                      <p className="text-white text-base mb-1">
                        Introductory Video
                      </p>
                      <p className="text-[#666666] text-xs mb-4">
                        Video available
                      </p>
                      <a
                        href={user.videoCloudinaryUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-block bg-[#2a2a2a] border border-[#393939] text-white text-xs px-6 py-2 rounded-lg hover:bg-[#333333] transition-colors"
                      >
                        Play Video
                      </a>
                    </div>
                  </div>
                </div>
              )}

              {/* Personal Information */}
              {(user.dateOfBirth ||
                user.contactNumber ||
                user.address ||
                user.occupation) && (
                <div className="mt-6">
                  <h3 className="text-white text-sm font-medium mb-3">
                    Personal Information
                  </h3>
                  <div className="bg-[#1f1f1f] border border-[#2a2a2a] rounded-lg p-4 space-y-2 text-xs">
                    {user.dateOfBirth && (
                      <p className="text-[#b5b5b5]">
                        <span className="text-[#666666]">Date of Birth:</span>{" "}
                        {user.dateOfBirth}
                      </p>
                    )}
                    {user.contactNumber && (
                      <p className="text-[#b5b5b5]">
                        <span className="text-[#666666]">Contact:</span>{" "}
                        {user.contactNumber}
                      </p>
                    )}
                    {user.address && (
                      <p className="text-[#b5b5b5]">
                        <span className="text-[#666666]">Address:</span>{" "}
                        {user.address}
                      </p>
                    )}
                    {user.occupation && (
                      <p className="text-[#b5b5b5]">
                        <span className="text-[#666666]">Occupation:</span>{" "}
                        {user.occupation}
                      </p>
                    )}
                    {user.maritalStatus && (
                      <p className="text-[#b5b5b5]">
                        <span className="text-[#666666]">Marital Status:</span>{" "}
                        {user.maritalStatus}
                      </p>
                    )}
                    {user.incomeRange && (
                      <p className="text-[#b5b5b5]">
                        <span className="text-[#666666]">Income Range:</span>{" "}
                        {user.incomeRange}
                      </p>
                    )}
                    {user.amountToInvest && (
                      <p className="text-[#b5b5b5]">
                        <span className="text-[#666666]">
                          Amount to Invest:
                        </span>{" "}
                        {user.amountToInvest}
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Footer Actions */}
          <div className="p-6 border-t border-[#2a2a2a] space-y-3">
            {user.validationStatus === "pending" && (
              <div>
                <label className="block text-white text-xs mb-2">
                  Rejection Reason (required if rejecting):
                </label>
                <textarea
                  value={rejectionReason}
                  onChange={(e) => setRejectionReason(e.target.value)}
                  placeholder="Enter reason for rejection..."
                  className="w-full bg-[#0d0d0d] border border-[#2a2a2a] text-white text-xs p-2 rounded-lg focus:border-[#00b05e] focus:outline-none resize-none"
                  rows={3}
                />
              </div>
            )}
            <div className="flex gap-3">
              <button
                onClick={handleApprove}
                disabled={loading || user.validationStatus === "approved"}
                className="flex-1 bg-[#00b05e] text-black text-xs font-medium py-3 rounded-lg hover:bg-[#00a055] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? "Processing..." : "Approve KYC"}
              </button>
              <button
                onClick={handleReject}
                disabled={loading || user.validationStatus === "rejected"}
                className="flex-1 border-2 border-[#ff4c4c] text-[#ff4c4c] text-xs font-medium py-3 rounded-lg hover:bg-[#ff4c4c]/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? "Processing..." : "Reject KYC"}
              </button>
            </div>
            {user.validationStatus !== "pending" && (
              <p className="text-[#666666] text-xs text-center">
                Status: {user.validationStatus.toUpperCase()}
              </p>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
