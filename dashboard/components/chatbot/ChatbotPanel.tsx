"use client";

import { useState, useRef, useEffect } from "react";
import { X, Send, Bot, User } from "lucide-react";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

interface ChatbotPanelProps {
  onClose: () => void;
}

export default function ChatbotPanel({ onClose }: ChatbotPanelProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "1",
      role: "assistant",
      content:
        "Hi! I'm your investment assistant. Ask me about any stock or report and I'll help you analyze it.",
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim()) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: input,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    const question = input;
    setInput("");
    setIsLoading(true);

    try {
      // Get session ID from localStorage (user-based) or generate default
      const userId =
        localStorage.getItem("userEmail") ||
        localStorage.getItem("userId") ||
        "default";
      const sessionId = `user_${userId}`;

      // Call FinRAG MCP HTTP API
      const mcpApiUrl =
        process.env.NEXT_PUBLIC_FINRAG_MCP_API_URL || "http://localhost:8002";
      const response = await fetch(`${mcpApiUrl}/chat/interactive`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          question: question,
          session_id: sessionId,
          method: "tree_traversal",
          top_k: 70,
          use_memory: true,
        }),
      });

      if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
      }

      const data = await response.json();

      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content:
          data.answer || "I couldn't generate an answer. Please try again.",
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error) {
      console.error("Chat error:", error);
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content:
          "Sorry, I encountered an error. Please make sure the FinRAG MCP API server is running on port 8002 and try again.",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="w-96 h-[622px] bg-gradient-to-b from-[#2a2a2a] to-[#1c1c1c] rounded-lg shadow-2xl border border-[#1a1a1a] flex flex-col overflow-hidden">
      {/* Header */}
      <div className="bg-[#161616] border-b border-[#1c1c1c] p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-[#00b05e] rounded-lg flex items-center justify-center">
            <Bot className="w-5 h-5 text-white" />
          </div>
          <div>
            <h3 className="text-white font-medium text-base">Chat Assistant</h3>
            <p className="text-[#666666] text-xs">Online</p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="w-5 h-5 flex items-center justify-center text-[#999999] hover:text-white transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-[#161616]">
        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex gap-3 ${
              message.role === "user" ? "justify-end" : "justify-start"
            }`}
          >
            {message.role === "assistant" && (
              <div className="w-8 h-8 bg-[#1a1a1a] rounded-full flex items-center justify-center flex-shrink-0">
                <Bot className="w-4 h-4 text-[#00b05e]" />
              </div>
            )}
            <div
              className={`max-w-[280px] rounded-lg p-3 ${
                message.role === "user"
                  ? "bg-[#00b05e] text-white"
                  : "bg-[#1a1a1a] text-[#cccccc]"
              }`}
            >
              <p className="text-sm whitespace-pre-wrap">{message.content}</p>
            </div>
            {message.role === "user" && (
              <div className="w-8 h-8 bg-[#1a1a1a] rounded-full flex items-center justify-center flex-shrink-0">
                <User className="w-4 h-4 text-[#999999]" />
              </div>
            )}
          </div>
        ))}
        {isLoading && (
          <div className="flex gap-3 justify-start">
            <div className="w-8 h-8 bg-[#1a1a1a] rounded-full flex items-center justify-center">
              <Bot className="w-4 h-4 text-[#00b05e]" />
            </div>
            <div className="bg-[#1a1a1a] rounded-lg p-3">
              <div className="flex gap-1">
                <div className="w-2 h-2 bg-[#00b05e] rounded-full animate-bounce" />
                <div
                  className="w-2 h-2 bg-[#00b05e] rounded-full animate-bounce"
                  style={{ animationDelay: "0.1s" }}
                />
                <div
                  className="w-2 h-2 bg-[#00b05e] rounded-full animate-bounce"
                  style={{ animationDelay: "0.2s" }}
                />
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="bg-[#161616] border-t border-[#1c1c1c] p-4">
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Ask me about any stock or report…"
            className="flex-1 bg-[#0d0d0d] border border-[#2a2a2a] rounded-lg px-4 py-3 text-white text-sm placeholder-[#666666] focus:outline-none focus:border-[#00b05e]"
            disabled={isLoading}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="w-10 h-10 bg-[#00b05e] rounded-lg flex items-center justify-center hover:bg-[#00a050] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Send className="w-4 h-4 text-white" />
          </button>
        </div>
      </div>
    </div>
  );
}
