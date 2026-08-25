"""
Utility functions for FinRAG.
"""
from typing import List, Dict, Any
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity


def calculate_similarity(embedding1: np.ndarray, embedding2: np.ndarray) -> float:
    """
    Calculate cosine similarity between two embeddings.
    
    Args:
        embedding1: First embedding
        embedding2: Second embedding
    
    Returns:
        Similarity score (0-1)
    """
    return float(cosine_similarity([embedding1], [embedding2])[0][0])


def format_financial_number(value: float, prefix: str = "$", suffix: str = "") -> str:
    """
    Format a number as a financial value.
    
    Args:
        value: Numeric value
        prefix: Prefix (e.g., "$")
        suffix: Suffix (e.g., "M", "B")
    
    Returns:
        Formatted string
    """
    if value >= 1e9:
        return f"{prefix}{value/1e9:.2f}B{suffix}"
    elif value >= 1e6:
        return f"{prefix}{value/1e6:.2f}M{suffix}"
    elif value >= 1e3:
        return f"{prefix}{value/1e3:.2f}K{suffix}"
    else:
        return f"{prefix}{value:.2f}{suffix}"


def extract_financial_entities(text: str) -> Dict[str, List[str]]:
    """
    Extract financial entities from text using simple pattern matching.
    For production use, consider using spaCy or other NER models.
    
    Args:
        text: Input text
    
    Returns:
        Dictionary of entity types and their values
    """
    import re
    
    entities = {
        "money": [],
        "percent": [],
        "dates": []
    }
    
    # Extract monetary amounts (e.g., $150M, $1.5B)
    money_pattern = r'\$[\d,]+(?:\.\d+)?[KMB]?'
    entities["money"] = re.findall(money_pattern, text)
    
    # Extract percentages (e.g., 25%, 12.5%)
    percent_pattern = r'\d+(?:\.\d+)?%'
    entities["percent"] = re.findall(percent_pattern, text)
    
    # Extract years (e.g., 2024, 2023)
    year_pattern = r'\b(19|20)\d{2}\b'
    entities["dates"] = re.findall(year_pattern, text)
    
    return entities


def merge_chunks_by_similarity(
    chunks: List[Dict[str, Any]],
    embeddings: np.ndarray,
    threshold: float = 0.8
) -> List[Dict[str, Any]]:
    """
    Merge similar chunks to reduce redundancy.
    
    Args:
        chunks: List of chunks
        embeddings: Chunk embeddings
        threshold: Similarity threshold for merging
    
    Returns:
        Merged chunks
    """
    if len(chunks) <= 1:
        return chunks
    
    merged = []
    used = set()
    
    for i in range(len(chunks)):
        if i in used:
            continue
        
        current_chunk = chunks[i]
        current_text = [current_chunk["text"]]
        used.add(i)
        
        # Find similar chunks
        for j in range(i + 1, len(chunks)):
            if j in used:
                continue
            
            sim = calculate_similarity(embeddings[i], embeddings[j])
            if sim >= threshold:
                current_text.append(chunks[j]["text"])
                used.add(j)
        
        # Create merged chunk
        merged_chunk = {
            "text": "\n\n".join(current_text),
            "chunk_id": current_chunk["chunk_id"],
            "merged_from": len(current_text)
        }
        merged.append(merged_chunk)
    
    return merged


def truncate_text(text: str, max_length: int = 500, suffix: str = "...") -> str:
    """
    Truncate text to maximum length.
    
    Args:
        text: Input text
        max_length: Maximum length
        suffix: Suffix to append
    
    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix
