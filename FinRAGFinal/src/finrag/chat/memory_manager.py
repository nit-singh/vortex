"""
Chat Memory Manager - Session-based conversation history storage.

This module provides memory management for interactive chat sessions,
storing the last N conversation turns per session.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from collections import defaultdict

logger = logging.getLogger(__name__)


class ConversationTurn:
    """Represents a single conversation turn (query-response pair)."""
    
    def __init__(self, query: str, response: str, timestamp: Optional[datetime] = None):
        """
        Initialize a conversation turn.
        
        Args:
            query: User's query/question
            response: Assistant's response
            timestamp: Timestamp of the conversation (default: now)
        """
        self.query = query
        self.response = response
        self.timestamp = timestamp or datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "query": self.query,
            "response": self.response,
            "timestamp": self.timestamp.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationTurn":
        """Create from dictionary."""
        timestamp = datetime.fromisoformat(data["timestamp"]) if isinstance(data["timestamp"], str) else data.get("timestamp")
        return cls(
            query=data["query"],
            response=data["response"],
            timestamp=timestamp
        )


class ChatMemoryManager:
    """
    Manages conversation memory for chat sessions.
    
    Stores the last N conversation turns per session_id.
    Memory is stored in-memory (can be extended to Redis/DB later).
    
    Attributes:
        memory_size: Maximum number of conversation turns to store per session
        sessions: Dictionary mapping session_id to list of ConversationTurn objects
    """
    
    def __init__(self, memory_size: int = 5):
        """
        Initialize the memory manager.
        
        Args:
            memory_size: Maximum number of conversation turns to remember per session (default: 5)
        """
        self.memory_size = memory_size
        self.sessions: Dict[str, List[ConversationTurn]] = defaultdict(list)
        logger.info(f"ChatMemoryManager initialized with memory_size={memory_size}")
    
    def store(
        self, 
        session_id: str, 
        query: str, 
        response: str,
        timestamp: Optional[datetime] = None
    ) -> None:
        """
        Store a conversation turn for a session.
        
        Args:
            session_id: Unique session identifier
            query: User's query
            response: Assistant's response
            timestamp: Optional timestamp (default: now)
        """
        turn = ConversationTurn(query=query, response=response, timestamp=timestamp)
        self.sessions[session_id].append(turn)
        
        # Keep only the last N turns
        if len(self.sessions[session_id]) > self.memory_size:
            self.sessions[session_id] = self.sessions[session_id][-self.memory_size:]
        
        logger.debug(
            f"Stored conversation turn for session '{session_id}' "
            f"(total turns: {len(self.sessions[session_id])})"
        )
    
    def retrieve(self, session_id: str, max_turns: Optional[int] = None) -> List[ConversationTurn]:
        """
        Retrieve conversation history for a session.
        
        Args:
            session_id: Session identifier
            max_turns: Maximum number of turns to retrieve (default: memory_size)
            
        Returns:
            List of ConversationTurn objects, ordered chronologically (oldest first)
        """
        turns = self.sessions.get(session_id, [])
        if max_turns is not None:
            turns = turns[-max_turns:]  # Get last N turns
        return turns.copy()
    
    def retrieve_last_n(self, session_id: str, n: int = 5) -> List[ConversationTurn]:
        """
        Retrieve the last N conversation turns for a session.
        
        Args:
            session_id: Session identifier
            n: Number of turns to retrieve (default: 5)
            
        Returns:
            List of last N ConversationTurn objects
        """
        return self.retrieve(session_id, max_turns=n)
    
    def format_context(self, session_id: str, max_turns: Optional[int] = None) -> str:
        """
        Format conversation history as context string for LLM.
        
        Args:
            session_id: Session identifier
            max_turns: Maximum number of turns to include (default: memory_size)
            
        Returns:
            Formatted context string with conversation history
        """
        turns = self.retrieve(session_id, max_turns=max_turns)
        
        if not turns:
            return ""
        
        lines = ["## Previous Conversation History"]
        lines.append("")
        
        for i, turn in enumerate(turns, 1):
            lines.append(f"**Previous Query {i}:** {turn.query}")
            # Truncate long responses for context efficiency
            response = turn.response
            if len(response) > 500:
                response = response[:500] + "..."
            lines.append(f"**Previous Response {i}:** {response}")
            lines.append("")
        
        return "\n".join(lines)
    
    def clear_session(self, session_id: str) -> bool:
        """
        Clear conversation history for a specific session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if session existed and was cleared, False otherwise
        """
        if session_id in self.sessions:
            del self.sessions[session_id]
            logger.info(f"Cleared memory for session '{session_id}'")
            return True
        return False
    
    def clear_all(self) -> None:
        """Clear all conversation history."""
        self.sessions.clear()
        logger.info("Cleared all conversation memory")
    
    def get_session_count(self, session_id: str) -> int:
        """
        Get the number of conversation turns stored for a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Number of conversation turns
        """
        return len(self.sessions.get(session_id, []))
    
    def has_session(self, session_id: str) -> bool:
        """
        Check if a session has any stored conversations.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if session exists and has conversations
        """
        return session_id in self.sessions and len(self.sessions[session_id]) > 0
    
    def get_all_sessions(self) -> List[str]:
        """
        Get list of all session IDs with stored conversations.
        
        Returns:
            List of session IDs
        """
        return list(self.sessions.keys())
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about stored memory.
        
        Returns:
            Dictionary with statistics
        """
        total_sessions = len(self.sessions)
        total_turns = sum(len(turns) for turns in self.sessions.values())
        
        return {
            "total_sessions": total_sessions,
            "total_conversation_turns": total_turns,
            "memory_size_per_session": self.memory_size,
            "average_turns_per_session": total_turns / total_sessions if total_sessions > 0 else 0
        }

