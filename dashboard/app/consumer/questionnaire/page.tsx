"use client";

import { useState, useRef, useEffect } from "react";
import React from "react";
import { useRouter } from "next/navigation";
import { ChevronDown, Upload, Video } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { authApi } from "@/lib/api";
import { uploadVideoToCloudinary, uploadDocumentToCloudinary } from "@/lib/cloudinary";
import { encryptFile } from "@/lib/encryption";
import { getUserId, isValidUserId } from "@/lib/userUtils";

interface FormData {
  // Step 1: Personal Information
  fullName: string;
  dateOfBirth: string;
  email: string;
  contactNumber: string;
  countryCode: string;
  // Step 2: Address Information
  addressLine1: string;
  addressLine2: string;
  city: string;
  state: string;
  pinCode: string;
  // Step 3: Additional Details
  main_occupation: string;
  maritalStatus: string;
  citizenship: string;
  incomeRange: string;
  amountToInvest: string;
  dependents: string;
  dependentDetails: Array<{
    name: string;
    address: string;
    relation: string;
  }>;
  // Step 4: Investment Questions
  investmentQ1: string;
  investmentQ2: string;
  investmentQ3: string;
  investmentQ4: string;
  investmentQ5: string;
  investmentQ6: string;
  // Step 5: Documents (encrypted base64 strings)
  aadhaarFile: string | null;
  panCardFile: string | null;
  itrDocumentFile: string | null;
  // Keep original file names for reference
  aadhaarFileName: string | null;
  panCardFileName: string | null;
  itrDocumentFileName: string | null;
  // Keep MIME types for document processing
  aadhaarMimeType: string | null;
  panCardMimeType: string | null;
  itrDocumentMimeType: string | null;
  // Step 6: Video
  videoBlob: Blob | null;
  videoCloudinaryUrl: string | null;
}

const INVESTMENT_QUESTIONS = [
  {
    question:
      "Which statement best describes your typical approach to investing?",
    options: [
      "A) I have a clear, well-researched strategy and I follow it.",
      'B) I mostly follow market trends and news, trying to buy what\'s "hot."',
      "C) I get tips from friends, family, or social media.",
      "D) I don't really have an approach; I just buy things and hope.",
    ],
  },
  {
    question: "How often do you typically check your investment portfolio?",
    options: [
      "A) Multiple times a day.",
      "B) Once a day.",
      "C) A few times a week.",
      "D) A few times a month or less.",
    ],
  },
  {
    question:
      "You own two stocks. Stock A is up 30%. Stock B is down 30%. You need to sell one to raise cash for a small emergency. Which do you sell?",
    options: [
      "A) Sell Stock A (the winner).",
      "B) Sell Stock B (the loser).",
      "C) Sell half of each.",
    ],
  },
  {
    question:
      "What is your ideal level of involvement in the day-to-day management of your portfolio?",
    options: [
      'A) Fully Delegated: "You\'re the expert. Handle everything for me and just send me the reports."',
      'B) Collaborative: "I want to be involved in big-picture strategy and approve major changes, but you handle the details."',
      'C) Hands-On: "I want to discuss and approve most, if not all, of the trades you recommend."',
    ],
  },
  {
    question:
      "When you review your portfolio's performance, what is the primary benchmark you will judge its success against?",
    options: [
      'A) Absolute Return: "Did I make money? (i.e., is the value higher than what I put in?)"',
      'B) Market Benchmark: "Did I beat a specific index (e.g., the S&P 500 or Nifty 50)?"',
      'C) Goal-Based: "Am I on track to meet my long-term goal (e.g., retirement, buying a home)?"',
      'D) Peer Comparison: "Did I do better than my friends/family?"',
    ],
  },
  {
    question:
      '"The market is down 10% in a single week. What do you expect from me?"',
    options: [
      "A) A proactive phone call or email explaining what's happening, what you're doing, and why I shouldn't panic.",
      "B) Nothing. I trust you're handling it. Just stick to the plan we agreed on.",
      "C) A detailed report of what you sold or bought.",
    ],
  },
];

export default function QuestionnairePage() {
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState(1);
  const [currentQuestion, setCurrentQuestion] = useState(1);
  const [loading, setLoading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<string>("");
  const [formData, setFormData] = useState<FormData>({
    fullName: "",
    dateOfBirth: "",
    email: "",
    contactNumber: "",
    countryCode: "+91",
    addressLine1: "",
    addressLine2: "",
    city: "",
    state: "",
    pinCode: "",
    main_occupation: "",
    maritalStatus: "",
    citizenship: "",
    incomeRange: "",
    amountToInvest: "",
    dependents: "0",
    dependentDetails: [],
    investmentQ1: "",
    investmentQ2: "",
    investmentQ3: "",
    investmentQ4: "",
    investmentQ5: "",
    investmentQ6: "",
    aadhaarFile: null,
    panCardFile: null,
    itrDocumentFile: null,
    aadhaarFileName: null,
    panCardFileName: null,
    itrDocumentFileName: null,
    aadhaarMimeType: null,
    panCardMimeType: null,
    itrDocumentMimeType: null,
    videoBlob: null,
    videoCloudinaryUrl: null,
  });

  // Video recording state
  const [isRecording, setIsRecording] = useState(false);
  const [recordedVideo, setRecordedVideo] = useState<string | null>(null);
  const [mediaStream, setMediaStream] = useState<MediaStream | null>(null);
  const videoPreviewRef = useRef<HTMLVideoElement | null>(null);
  const [recordingTime, setRecordingTime] = useState(0);
  const [mediaRecorder, setMediaRecorder] = useState<MediaRecorder | null>(
    null
  );

  const handleInputChange = (
    e: React.ChangeEvent<
      HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
    >
  ) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleFileChange = async (
    e: React.ChangeEvent<HTMLInputElement>,
    fieldName: "aadhaarFile" | "panCardFile" | "itrDocumentFile"
  ) => {
    const file = e.target.files?.[0] || null;
    if (file) {
      // Validate file size (10MB max)
      const maxSize = 10 * 1024 * 1024; // 10MB in bytes
      if (file.size > maxSize) {
        alert(`File size exceeds 10MB limit. Please choose a smaller file.`);
        return;
      }

      try {
        // Encrypt the file in the frontend
        const encryptedBase64 = await encryptFile(file);
        setFormData((prev) => ({
          ...prev,
          [fieldName]: encryptedBase64,
          [`${fieldName}Name`]: file.name,
          [`${fieldName.replace("File", "")}MimeType`]: file.type,
        }));
      } catch (error) {
        console.error("Error encrypting file:", error);
        alert("Failed to encrypt file. Please try again.");
      }
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = async (
    e: React.DragEvent,
    fieldName: "aadhaarFile" | "panCardFile" | "itrDocumentFile"
  ) => {
    e.preventDefault();
    e.stopPropagation();
    const file = e.dataTransfer.files?.[0] || null;
    if (file) {
      const maxSize = 10 * 1024 * 1024; // 10MB
      if (file.size > maxSize) {
        alert(`File size exceeds 10MB limit. Please choose a smaller file.`);
        return;
      }

      try {
        // Encrypt the file in the frontend
        const encryptedBase64 = await encryptFile(file);
        setFormData((prev) => ({
          ...prev,
          [fieldName]: encryptedBase64,
          [`${fieldName}Name`]: file.name,
          [`${fieldName.replace("File", "")}MimeType`]: file.type,
        }));
      } catch (error) {
        console.error("Error encrypting file:", error);
        alert("Failed to encrypt file. Please try again.");
      }
    }
  };

  // Video recording functions
  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: true,
      });
      setMediaStream(stream);

      // Set the stream to video element
      if (videoPreviewRef.current) {
        videoPreviewRef.current.srcObject = stream;
        videoPreviewRef.current.play().catch((err) => {
          console.error("Error playing video:", err);
        });
      }

      const recorder = new MediaRecorder(stream, {
        mimeType: "video/webm;codecs=vp8,opus",
      });

      const chunks: Blob[] = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          chunks.push(e.data);
        }
      };

      recorder.onstop = () => {
        const blob = new Blob(chunks, { type: "video/webm" });
        const videoUrl = URL.createObjectURL(blob);
        setRecordedVideo(videoUrl);
        setFormData((prev) => ({ ...prev, videoBlob: blob }));
        setRecordingTime(0);
      };

      recorder.start();
      setMediaRecorder(recorder);
      setIsRecording(true);

      // Timer for recording duration
      const timer = setInterval(() => {
        setRecordingTime((prev) => {
          const newTime = prev + 1;
          // Auto-stop at 30 seconds
          if (newTime >= 30) {
            stopRecording();
            clearInterval(timer);
            return 30;
          }
          return newTime;
        });
      }, 1000);
    } catch (error) {
      console.error("Error accessing camera:", error);
      alert("Unable to access camera. Please check permissions.");
    }
  };

  const stopRecording = () => {
    if (mediaRecorder && isRecording) {
      mediaRecorder.stop();
      setIsRecording(false);
    }
    if (mediaStream) {
      mediaStream.getTracks().forEach((track) => track.stop());
      setMediaStream(null);
    }
    if (videoPreviewRef.current) {
      videoPreviewRef.current.srcObject = null;
    }
  };

  const retakeVideo = () => {
    if (recordedVideo) {
      URL.revokeObjectURL(recordedVideo);
      setRecordedVideo(null);
    }
    setFormData((prev) => ({ ...prev, videoBlob: null }));
    setRecordingTime(0);
    if (mediaStream) {
      mediaStream.getTracks().forEach((track) => track.stop());
      setMediaStream(null);
    }
  };

  // Update video element when stream changes
  useEffect(() => {
    if (mediaStream && videoPreviewRef.current) {
      videoPreviewRef.current.srcObject = mediaStream;
      videoPreviewRef.current.play().catch((err: Error) => {
        console.error("Error playing video:", err);
      });
    }
  }, [mediaStream]);

  // Check authentication and userId on mount
  useEffect(() => {
    const checkAuthAndUserId = async () => {
      const isAuthenticated = localStorage.getItem("isAuthenticated");

      if (isAuthenticated !== "true") {
        router.push("/login");
        return;
      }

      // Validate userId exists and is valid format
      let userId =
        localStorage.getItem("userId") || sessionStorage.getItem("userId");

      if (!userId || !isValidUserId(userId)) {
        // Try to recover userId from backend
        userId = await getUserId();

        if (!userId || !isValidUserId(userId)) {
          // Cannot recover userId, redirect to login
          alert("Session expired. Please login again.");
          router.push("/login");
          return;
        }
      }
    };

    checkAuthAndUserId();
  }, [router]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (mediaStream) {
        mediaStream.getTracks().forEach((track) => track.stop());
      }
      if (recordedVideo) {
        URL.revokeObjectURL(recordedVideo);
      }
    };
  }, [mediaStream, recordedVideo]);

  const handleNext = () => {
    if (currentStep === 4) {
      // Handle question navigation within Step 4
      if (currentQuestion < 6) {
        setCurrentQuestion(currentQuestion + 1);
      } else {
        // All questions answered, move to step 5
        setCurrentStep(5);
      }
    } else if (currentStep < 6) {
      const nextStep = currentStep + 1;
      setCurrentStep(nextStep);
      if (nextStep === 4) {
        // Reset to question 1 when entering step 4
        setCurrentQuestion(1);
      }
    }
  };

  const handleBack = () => {
    if (currentStep === 4 && currentQuestion > 1) {
      setCurrentQuestion(currentQuestion - 1);
    } else if (currentStep > 1) {
      if (currentStep === 4) {
        setCurrentQuestion(6);
      }
      setCurrentStep(currentStep - 1);
      if (currentStep === 5) {
        // When going back from step 6 to step 5, no special handling needed
      }
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (currentStep === 4) {
      // Handle question navigation within Step 4
      if (currentQuestion < 6) {
        handleNext();
        return;
      }
      // Move to step 5 after all questions answered
      handleNext();
      return;
    } else if (currentStep === 5) {
      // Move to step 6 after documents uploaded
      handleNext();
      return;
    } else if (currentStep === 6) {
      // Final submission after video uploaded
      setLoading(true);
      setUploadProgress("");
      try {
        // Get userId using utility function (checks localStorage, sessionStorage, and backend)
        let userId = await getUserId();

        if (!userId || !isValidUserId(userId)) {
          // Cannot recover userId, redirect to login
          alert("Session expired. Unable to verify user. Please login again.");
          router.push("/login");
          setLoading(false);
          return;
        }

        // Upload documents to Cloudinary
        const documentUrls: {
          aadhaar?: string;
          pan?: string;
          itr?: string;
        } = {};

        if (formData.aadhaarFile && formData.aadhaarMimeType) {
          try {
            setUploadProgress("Uploading Aadhaar document to Cloudinary...");
            const aadhaarResponse = await uploadDocumentToCloudinary(
              formData.aadhaarFile,
              userId,
              "aadhaar",
              formData.aadhaarMimeType
            );
            documentUrls.aadhaar = aadhaarResponse.secure_url;
          } catch (uploadError: any) {
            console.error("Aadhaar upload failed:", uploadError);
            // Continue with other uploads even if one fails
          }
        }

        if (formData.panCardFile && formData.panCardMimeType) {
          try {
            setUploadProgress("Uploading PAN card to Cloudinary...");
            const panResponse = await uploadDocumentToCloudinary(
              formData.panCardFile,
              userId,
              "pan",
              formData.panCardMimeType
            );
            documentUrls.pan = panResponse.secure_url;
          } catch (uploadError: any) {
            console.error("PAN upload failed:", uploadError);
            // Continue with other uploads even if one fails
          }
        }

        if (formData.itrDocumentFile && formData.itrDocumentMimeType) {
          try {
            setUploadProgress("Uploading ITR document to Cloudinary...");
            const itrResponse = await uploadDocumentToCloudinary(
              formData.itrDocumentFile,
              userId,
              "itr",
              formData.itrDocumentMimeType
            );
            documentUrls.itr = itrResponse.secure_url;
          } catch (uploadError: any) {
            console.error("ITR upload failed:", uploadError);
            // Continue with other uploads even if one fails
          }
        }

        // Upload video to Cloudinary if video blob exists
        let videoUrl = formData.videoCloudinaryUrl;
        if (formData.videoBlob && !videoUrl) {
          try {
            setUploadProgress("Uploading video to Cloudinary...");
            const cloudinaryResponse = await uploadVideoToCloudinary(
              formData.videoBlob,
              userId
            );

            // Store Cloudinary URL
            videoUrl = cloudinaryResponse.secure_url;
            setFormData((prev) => ({
              ...prev,
              videoCloudinaryUrl: videoUrl,
            }));
          } catch (uploadError: any) {
            alert(
              `Video upload failed: ${
                uploadError.message || "Unknown error"
              }. Please try again.`
            );
            setLoading(false);
            return;
          }
        }

        // Submit questionnaire data to backend (files are already encrypted)
        setUploadProgress("Submitting questionnaire data...");
        try {
          await authApi.submitQuestionnaire(userId, formData, videoUrl, documentUrls);
        } catch (submitError: any) {
          // Even if submission fails, try to update status
          console.error("Questionnaire submission error:", submitError);
        }

        // Update questionnaire status
        setUploadProgress("Saving questionnaire status...");
        await authApi.updateQuestionnaireStatus(userId, true);
        localStorage.setItem("isQuestionnaireSubmitted", "true");
        localStorage.setItem("questionnaireCompleted", "true");

        // Store video URL in localStorage if available
        if (videoUrl) {
          localStorage.setItem("videoCloudinaryUrl", videoUrl);
        }

        setUploadProgress("Complete!");
        router.push("/consumer/dashboard");
      } catch (error) {
        console.error("Failed to submit questionnaire:", error);
        alert("Failed to submit questionnaire. Please try again.");
      } finally {
        setLoading(false);
      }
    } else if (currentStep < 4) {
      handleNext();
      return;
    }
  };

  const saveAndFinishLater = () => {
    localStorage.setItem("questionnaireData", JSON.stringify(formData));
    router.push("/consumer/dashboard");
  };

  const renderProgressBar = () => {
    return (
      <div className="flex items-center gap-2">
        <div className="flex gap-1.5">
          {[1, 2, 3, 4, 5, 6].map((step) => (
            <div
              key={step}
              className={`h-1 w-9 rounded-full transition-colors ${
                step <= currentStep ? "bg-[#00b05e]" : "bg-[#1f1f1f]"
              }`}
            />
          ))}
        </div>
        <p className="text-[#6a7282] text-xs">Step {currentStep} of 6</p>
      </div>
    );
  };

  const renderStep1 = () => (
    <div className="space-y-6">
      <div className="space-y-2">
        <label className="text-white text-sm block">Full Name</label>
        <Input
          name="fullName"
          value={formData.fullName}
          onChange={handleInputChange}
          placeholder="Enter your full name"
          className="bg-[#1f1f1f] border-[#2a2a2a] text-white placeholder:text-[#6a7282] h-10 rounded-lg px-3 text-sm"
          required
        />
      </div>

      <div className="space-y-2">
        <label className="text-white text-sm block">Date of Birth</label>
        <Input
          name="dateOfBirth"
          type="date"
          value={formData.dateOfBirth}
          onChange={handleInputChange}
          placeholder="DD/MM/YYYY"
          className="bg-[#1f1f1f] border-[#2a2a2a] text-white placeholder:text-[#6a7282] h-10 rounded-lg px-3 text-sm"
          required
        />
      </div>

      <div className="space-y-2">
        <label className="text-white text-sm block">Email Address</label>
        <Input
          name="email"
          type="email"
          value={formData.email}
          onChange={handleInputChange}
          placeholder="your.email@example.com"
          className="bg-[#1f1f1f] border-[#2a2a2a] text-white placeholder:text-[#6a7282] h-10 rounded-lg px-3 text-sm"
          required
        />
      </div>

      <div className="space-y-2">
        <label className="text-white text-sm block">Contact Number</label>
        <div className="flex gap-2">
          <div className="relative w-24">
            <select
              name="countryCode"
              value={formData.countryCode}
              onChange={handleInputChange}
              className="bg-[#1f1f1f] border-[#2a2a2a] border text-white h-10 rounded-lg px-3 pr-8 appearance-none cursor-pointer w-full text-sm"
            >
              <option value="+91">+91</option>
              <option value="+1">+1</option>
              <option value="+44">+44</option>
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-white pointer-events-none" />
          </div>
          <Input
            name="contactNumber"
            value={formData.contactNumber}
            onChange={handleInputChange}
            placeholder="Enter your contact number"
            className="bg-[#1f1f1f] border-[#2a2a2a] text-white placeholder:text-[#6a7282] h-10 rounded-lg px-3 flex-1 text-sm"
            required
          />
        </div>
      </div>
    </div>
  );

  const renderStep2 = () => (
    <div className="space-y-[18.36px]">
      <h3 className="text-white text-[14px] leading-[18.36px]">Address</h3>

      <div className="space-y-[6.12px]">
        <label className="text-white text-[14px] leading-[18.36px] block">
          Address Line 1
        </label>
        <Input
          name="addressLine1"
          value={formData.addressLine1}
          onChange={handleInputChange}
          placeholder="Street address"
          className="bg-[#1f1f1f] border-[#2a2a2a] text-white placeholder:text-[#6a7282] h-[38.25px] rounded-[7.65px]"
          required
        />
      </div>

      <div className="space-y-[6.12px]">
        <label className="text-white text-[14px] leading-[18.36px] block">
          Address Line 2
        </label>
        <Input
          name="addressLine2"
          value={formData.addressLine2}
          onChange={handleInputChange}
          placeholder="Apartment, suite, etc. (optional)"
          className="bg-[#1f1f1f] border-[#2a2a2a] text-white placeholder:text-[#6a7282] h-[38.25px] rounded-[7.65px]"
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="space-y-2">
          <label className="text-white text-sm block">City</label>
          <Input
            name="city"
            value={formData.city}
            onChange={handleInputChange}
            placeholder="City"
            className="bg-[#1f1f1f] border-[#2a2a2a] text-white placeholder:text-[#6a7282] h-10 rounded-lg px-3 text-sm"
            required
          />
        </div>

        <div className="space-y-2">
          <label className="text-white text-sm block">State</label>
          <Input
            name="state"
            value={formData.state}
            onChange={handleInputChange}
            placeholder="State"
            className="bg-[#1f1f1f] border-[#2a2a2a] text-white placeholder:text-[#6a7282] h-10 rounded-lg px-3 text-sm"
            required
          />
        </div>
      </div>

      <div className="space-y-[6.12px]">
        <label className="text-white text-[14px] leading-[18.36px] block">
          PIN Code
        </label>
        <Input
          name="pinCode"
          value={formData.pinCode}
          onChange={handleInputChange}
          placeholder="Enter PIN code"
          className="bg-[#1f1f1f] border-[#2a2a2a] text-white placeholder:text-[#6a7282] h-[38.25px] rounded-[7.65px]"
          required
        />
      </div>
    </div>
  );

  const renderStep3 = () => (
    <div className="space-y-6">
      <div className="space-y-2">
        <label className="text-white text-sm block">Main Occupation</label>
        <div className="relative">
          <select
            name="main_occupation"
            value={formData.main_occupation}
            onChange={handleInputChange}
            className="bg-[#1f1f1f] border-[#2a2a2a] border text-white h-10 rounded-lg px-3 pr-8 appearance-none cursor-pointer w-full text-sm"
            required
          >
            <option value="">Select occupation</option>
            <option value="Salaried">Salaried</option>
            <option value="Business">Business</option>
            <option value="Professional">Professional</option>
            <option value="Student/Retired">Student/Retired</option>
          </select>
          <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-white pointer-events-none" />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="space-y-2">
          <label className="text-white text-sm block">Marital Status</label>
          <div className="relative">
            <select
              name="maritalStatus"
              value={formData.maritalStatus}
              onChange={handleInputChange}
              className="bg-[#1f1f1f] border-[#2a2a2a] border text-white h-10 rounded-lg px-3 pr-8 appearance-none cursor-pointer w-full text-sm"
              required
            >
              <option value="">Select status</option>
              <option value="Single">Single</option>
              <option value="Married">Married</option>
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-white pointer-events-none" />
          </div>
        </div>

        <div className="space-y-2">
          <label className="text-white text-sm block">Citizenship</label>
          <div className="relative">
            <select
              name="citizenship"
              value={formData.citizenship}
              onChange={handleInputChange}
              className="bg-[#1f1f1f] border-[#2a2a2a] border text-white h-10 rounded-lg px-3 pr-8 appearance-none cursor-pointer w-full text-sm"
              required
            >
              <option value="">Select citizenship</option>
              <option value="Indian">Indian</option>
              <option value="NRI">NRI</option>
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-white pointer-events-none" />
          </div>
        </div>
      </div>

      <div className="space-y-2">
        <label className="text-white text-sm block">Income Range</label>
        <div className="relative">
          <select
            name="incomeRange"
            value={formData.incomeRange}
            onChange={handleInputChange}
            className="bg-[#1f1f1f] border-[#2a2a2a] border text-white h-10 rounded-lg px-3 pr-8 appearance-none cursor-pointer w-full text-sm"
            required
          >
            <option value="">Select income range</option>
            <option value="< 5 Lakhs">Less than 5 Lakhs</option>
            <option value="5-10 Lakhs">5-10 Lakhs</option>
            <option value="10-25 Lakhs">10-25 Lakhs</option>
            <option value="25-50 Lakhs">25-50 Lakhs</option>
            <option value="50-100 Lakhs">50-100 Lakhs</option>
            <option value="> 100 Lakhs">More than 100 Lakhs</option>
          </select>
          <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-white pointer-events-none" />
        </div>
      </div>

      <div className="space-y-2">
        <label className="text-white text-sm block">Amount to Invest</label>
        <Input
          name="amountToInvest"
          type="number"
          value={formData.amountToInvest}
          onChange={handleInputChange}
          placeholder="Enter amount in INR"
          className="bg-[#1f1f1f] border-[#2a2a2a] text-white placeholder:text-[#6a7282] h-10 rounded-lg px-3 text-sm"
          min="0"
          required
        />
      </div>

      <div className="space-y-2">
        <label className="text-white text-sm block">Number of Dependents</label>
        <Input
          name="dependents"
          type="number"
          value={formData.dependents}
          onChange={(e) => {
            const count = parseInt(e.target.value) || 0;
            setFormData((prev) => {
              const newDependentDetails = Array(count).fill(null).map((_, index) => 
                prev.dependentDetails[index] || { name: "", address: "", relation: "" }
              );
              return {
                ...prev,
                dependents: e.target.value,
                dependentDetails: newDependentDetails.slice(0, count),
              };
            });
          }}
          placeholder="0"
          className="bg-[#1f1f1f] border-[#2a2a2a] text-white placeholder:text-[#6a7282] h-10 rounded-lg px-3 text-sm"
          min="0"
          required
        />
      </div>

      {parseInt(formData.dependents) > 0 && (
        <div className="space-y-4">
          <label className="text-white text-sm block">Dependent Details</label>
          {formData.dependentDetails.map((dependent, index) => (
            <div key={index} className="bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg p-4 space-y-3">
              <h4 className="text-white text-sm font-medium">Dependent {index + 1}</h4>
              <div className="grid grid-cols-1 gap-3">
                <Input
                  type="text"
                  value={dependent.name}
                  onChange={(e) => {
                    const newDetails = [...formData.dependentDetails];
                    newDetails[index] = { ...newDetails[index], name: e.target.value };
                    setFormData((prev) => ({ ...prev, dependentDetails: newDetails }));
                  }}
                  placeholder="Name"
                  className="bg-[#1f1f1f] border-[#2a2a2a] text-white placeholder:text-[#6a7282] h-10 rounded-lg px-3 text-sm"
                  required
                />
                <Input
                  type="text"
                  value={dependent.relation}
                  onChange={(e) => {
                    const newDetails = [...formData.dependentDetails];
                    newDetails[index] = { ...newDetails[index], relation: e.target.value };
                    setFormData((prev) => ({ ...prev, dependentDetails: newDetails }));
                  }}
                  placeholder="Relation (e.g., Spouse, Child, Parent)"
                  className="bg-[#1f1f1f] border-[#2a2a2a] text-white placeholder:text-[#6a7282] h-10 rounded-lg px-3 text-sm"
                  required
                />
                <textarea
                  value={dependent.address}
                  onChange={(e) => {
                    const newDetails = [...formData.dependentDetails];
                    newDetails[index] = { ...newDetails[index], address: e.target.value };
                    setFormData((prev) => ({ ...prev, dependentDetails: newDetails }));
                  }}
                  placeholder="Address"
                  className="bg-[#1f1f1f] border-[#2a2a2a] border text-white placeholder:text-[#6a7282] rounded-lg px-3 py-2 min-h-[80px] w-full resize-none text-sm"
                  rows={3}
                  required
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  const renderStep4 = () => {
    const question = INVESTMENT_QUESTIONS[currentQuestion - 1];
    const questionKey = `investmentQ${currentQuestion}` as keyof FormData;
    const selectedAnswer = formData[questionKey] as string;

    const handleOptionSelect = (option: string) => {
      setFormData((prev) => ({
        ...prev,
        [questionKey]: option,
      }));
    };

    return (
      <div className="bg-[#1a1a1a] border border-[#2a2a2a] rounded-xl p-8">
        <div className="flex items-center justify-between mb-6">
          <h3 className="text-[#00b05e] text-xl font-medium">
            Question {currentQuestion}
          </h3>
          <p className="text-[#666666] text-sm">{currentQuestion} of 6</p>
        </div>

        <h2 className="text-white text-base mb-6">{question.question}</h2>

        <div className="space-y-3">
          {question.options.map((option, index) => (
            <button
              key={index}
              type="button"
              onClick={() => handleOptionSelect(option)}
              className={`w-full text-left bg-[#111111] border border-[#2a2a2a] rounded-lg p-4 flex items-start gap-4 hover:border-[#00b05e] transition-colors ${
                selectedAnswer === option ? "border-[#00b05e]" : ""
              }`}
            >
              <div
                className={`mt-0.5 w-5 h-5 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${
                  selectedAnswer === option
                    ? "border-[#00b05e] bg-[#00b05e]"
                    : "border-[#666666]"
                }`}
              >
                {selectedAnswer === option && (
                  <div className="w-2 h-2 rounded-full bg-black" />
                )}
              </div>
              <p className="text-[#cccccc] text-base flex-1">{option}</p>
            </button>
          ))}
        </div>
      </div>
    );
  };

  const renderDocumentUpload = (
    title: string,
    description: string,
    fieldName: "aadhaarFile" | "panCardFile" | "itrDocumentFile",
    encryptedFile: string | null,
    fileName: string | null
  ) => {
    return (
      <div className="bg-[#1a1a1a] flex flex-col gap-3 items-start p-4 rounded-[10px] w-full">
        <div className="flex flex-col gap-1 items-start justify-center w-full">
          <p className="text-white text-sm leading-[18px]">{title}</p>
          <p className="text-[#99a1af] text-xs leading-[20px]">{description}</p>
        </div>
        <div
          onDragOver={handleDragOver}
          onDrop={(e) => handleDrop(e, fieldName)}
          className="border-2 border-[#364153] border-solid flex h-[229px] items-center justify-center px-5 py-6 rounded-[10px] w-full cursor-pointer hover:border-[#00b05e] transition-colors relative"
        >
          <input
            type="file"
            id={fieldName}
            accept=".jpg,.jpeg,.png,.pdf"
            onChange={(e) => handleFileChange(e, fieldName)}
            className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
          />
          <div className="flex flex-col items-center w-full">
            <div className="flex flex-col gap-3 items-center w-full">
              <div className="bg-[rgba(0,176,94,0.2)] flex items-center justify-center rounded-full size-12">
                <Upload className="size-6 text-[#00b05e]" />
              </div>
              <div className="flex flex-col gap-2 items-center text-center w-full">
                <p className="text-[#00b05e] text-sm leading-6">
                  {fileName || "Drag & drop or upload file"}
                </p>
                <p className="text-[#6a7282] text-xs leading-5">
                  JPG, PNG, PDF (Max 10MB)
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  };

  const renderStep5 = () => {
    return (
      <div className="space-y-4">
        <h3 className="text-white text-base mb-4">Upload Documents</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {renderDocumentUpload(
            "Aadhaar",
            "Upload your Aadhaar",
            "aadhaarFile",
            formData.aadhaarFile,
            formData.aadhaarFileName
          )}
          {renderDocumentUpload(
            "PAN Card",
            "Upload your PAN card",
            "panCardFile",
            formData.panCardFile,
            formData.panCardFileName
          )}
          {renderDocumentUpload(
            "ITR Document",
            "Upload your latest ITR",
            "itrDocumentFile",
            formData.itrDocumentFile,
            formData.itrDocumentFileName
          )}
        </div>
      </div>
    );
  };

  const renderStep6 = () => {
    const formatTime = (seconds: number) => {
      return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(
        2,
        "0"
      )}`;
    };

    return (
      <div className="space-y-4">
        <div className="bg-[#1a1a1a] flex flex-col gap-4 items-start p-4 rounded-[10px] w-full">
          <div className="flex items-start justify-between w-full">
            <div className="flex flex-col gap-1 items-start justify-center">
              <p className="text-white text-sm leading-[18px]">Video Record</p>
              <p className="text-[#99a1af] text-xs leading-[20px]">
                Record a verification video (5-30 seconds)
              </p>
            </div>
            {!isRecording && !recordedVideo && (
              <Button
                type="button"
                onClick={startRecording}
                className="bg-[#00b05e] text-black hover:bg-[#00a055] h-10 rounded-lg font-medium text-sm px-6"
              >
                Start Recording
              </Button>
            )}
            {recordedVideo && !isRecording && (
              <Button
                type="button"
                onClick={retakeVideo}
                variant="outline"
                className="border-[#2a2a2a] border text-[#d1d5dc] hover:bg-[#1f1f1f] h-10 rounded-lg font-medium text-sm px-6"
              >
                Retake
              </Button>
            )}
          </div>

          {/* Video Preview/Recording Area */}
          <div className="border-2 border-[#364153] border-solid flex flex-col items-center justify-center min-h-[300px] w-full rounded-[10px] overflow-hidden bg-black relative">
            {!recordedVideo && !isRecording && (
              <div className="flex flex-col items-center gap-3 p-8">
                <div className="bg-[rgba(0,176,94,0.2)] flex items-center justify-center rounded-full size-16">
                  <Video className="size-8 text-[#00b05e]" />
                </div>
                <p className="text-[#99a1af] text-sm text-center">
                  Click &quot;Start Recording&quot; to begin
                </p>
              </div>
            )}

            {/* Live Preview while recording */}
            {isRecording && (
              <div className="relative w-full h-full min-h-[300px]">
                <video
                  ref={videoPreviewRef}
                  autoPlay
                  playsInline
                  muted
                  className="w-full h-full object-cover"
                />
                <div className="absolute top-4 left-4 bg-red-600 text-white px-3 py-1 rounded-full flex items-center gap-2">
                  <div className="w-2 h-2 bg-white rounded-full animate-pulse" />
                  <span className="text-sm font-medium">
                    Recording {formatTime(recordingTime)}
                  </span>
                </div>
              </div>
            )}

            {/* Recorded Video Playback */}
            {recordedVideo && !isRecording && (
              <video
                src={recordedVideo}
                controls
                className="w-full h-full max-h-[400px] object-contain"
              />
            )}
          </div>

          {/* Controls */}
          <div className="flex flex-col gap-3 w-full">
            {isRecording && (
              <Button
                type="button"
                onClick={stopRecording}
                className="w-full bg-red-600 text-white hover:bg-red-700 h-10 rounded-lg font-medium text-sm"
              >
                Stop Recording
              </Button>
            )}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#0d0d0d] to-[#121212] flex items-start justify-center pt-8 pb-16 px-4 sm:px-6 lg:px-8">
      <div className="w-full max-w-2xl">
        {/* Main Content */}
        <div className="w-full">
          {/* Header */}
          <div className="mb-10">
            {renderProgressBar()}
            <h1 className="text-white text-3xl sm:text-4xl font-medium mt-6 mb-2">
              {currentStep === 4
                ? "Investor Onboarding – Determine investment style"
                : currentStep === 5
                ? "Investor Onboarding – Complete KYC"
                : currentStep === 6
                ? "Investor Onboarding – Complete KYC"
                : "Investor Onboarding – Verify your personal details"}
            </h1>
            <p className="text-[#99a1af] text-sm sm:text-base leading-relaxed">
              {currentStep === 4
                ? "Answer a few questions to help us understand your risk profile and preferences."
                : currentStep === 5
                ? "Submit your documents to complete verification"
                : currentStep === 6
                ? "Submit your documents to complete verification"
                : "This information is collected to verify your identity and meet regulatory requirements."}
            </p>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="w-full">
            <div className="space-y-6">
              {currentStep === 1 && renderStep1()}
              {currentStep === 2 && renderStep2()}
              {currentStep === 3 && renderStep3()}
              {currentStep === 4 && renderStep4()}
              {currentStep === 5 && renderStep5()}
              {currentStep === 6 && renderStep6()}
            </div>

            {/* Divider */}
            {currentStep < 4 && (
              <div className="border-t border-[#2a2a2a] my-6" />
            )}

            {/* Buttons */}
            <div className="flex flex-col sm:flex-row gap-3 pt-6">
              <Button
                type="submit"
                disabled={
                  loading ||
                  (currentStep === 4 &&
                    !formData[
                      `investmentQ${currentQuestion}` as keyof FormData
                    ]) ||
                  (currentStep === 5 &&
                    (!formData.aadhaarFile ||
                      !formData.panCardFile ||
                      !formData.itrDocumentFile)) ||
                  (currentStep === 6 && !formData.videoBlob)
                }
                className="flex-1 bg-[#00b05e] text-black hover:bg-[#00a055] h-10 rounded-lg font-medium text-sm disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading
                  ? uploadProgress || "Submitting..."
                  : currentStep === 6
                  ? "Finish"
                  : currentStep === 4 && currentQuestion === 6
                  ? "Continue"
                  : currentStep === 4
                  ? "Next"
                  : "Continue"}
              </Button>
              {currentStep < 4 && (
                <Button
                  type="button"
                  onClick={saveAndFinishLater}
                  variant="outline"
                  className="flex-1 border-[#2a2a2a] border text-[#d1d5dc] hover:bg-[#1f1f1f] h-10 rounded-lg font-medium text-sm"
                >
                  Save & Finish Later
                </Button>
              )}
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
