"use client";

import { useState } from "react";
import { MessageCircle, X } from "lucide-react";
import ChatbotPanel from "@/components/chatbot/ChatbotPanel";

export default function ChatbotButton() {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      {!isOpen && (
        <button
          onClick={() => setIsOpen(true)}
          className="fixed bottom-8 right-8 w-16 h-16 bg-[#00b05e] rounded-full shadow-lg flex items-center justify-center hover:bg-[#00a050] transition-colors z-50"
          title="Ask about reports or companies"
        >
          <MessageCircle className="w-7 h-7 text-white" />
        </button>
      )}
      {isOpen && (
        <div className="fixed bottom-8 right-8 z-50">
          <ChatbotPanel onClose={() => setIsOpen(false)} />
        </div>
      )}
    </>
  );
}
