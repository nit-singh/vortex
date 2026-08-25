"""ChromaDB VectorStore implementation for FinRAG."""

from __future__ import annotations
import logging
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass
from pathlib import Path
import json
import numpy as np

logger = logging.getLogger(__name__)

# Try to import ChromaDB
try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
    CHROMADB_ERROR = None
except Exception as e:
    CHROMADB_AVAILABLE = False
    CHROMADB_ERROR = str(e)
    chromadb = None
    Settings = None

# Preserve original ClusterNode import logic
try:
    from ..core.clustering import ClusterNode
except ImportError:
    import sys
    from pathlib import Path as _Path
    root_path = _Path(__file__).parent.parent.parent
    if str(root_path) not in sys.path:
        sys.path.insert(0, str(root_path))
    from finrag.core.clustering import ClusterNode


@dataclass
class ChromaConfig:
    """Configuration for ChromaDB vector store."""
    
    collection_name: str = "finrag_embeddings"
    persist_directory: Optional[str] = None
    dimension: int = 1536  # OpenAI embedding dimension
    
    def __post_init__(self) -> None:
        """Validate configuration."""
        if not CHROMADB_AVAILABLE:
            logger.warning(
                "ChromaDB not installed. Install with: pip install chromadb. "
                f"Underlying import error: {CHROMADB_ERROR}"
            )


class ChromaVectorStore:
    """Vector store using ChromaDB for persistent vector storage."""
    
    def __init__(self, config: Optional[ChromaConfig] = None) -> None:
        """
        Initialize ChromaDB vector store.
        
        Args:
            config: ChromaDB configuration (optional)
        """
        if not CHROMADB_AVAILABLE:
            raise RuntimeError(
                f"ChromaDB not installed or not available. "
                f"Install with: pip install chromadb. "
                f"Error: {CHROMADB_ERROR}"
            )
        
        self.config = config or ChromaConfig()
        self.collection_name = self.config.collection_name
        self.persist_directory = self.config.persist_directory
        
        # Core data (for compatibility with existing code)
        self.nodes: Dict[str, ClusterNode] = {}
        self.node_ids: List[str] = []
        self.embeddings: Optional[np.ndarray] = None
        self.embedding_cache: Dict[str, np.ndarray] = {}
        
        # State
        self.is_built: bool = False
        
        # Initialize ChromaDB client
        if self.persist_directory:
            # Persistent mode - store on disk
            self.client = chromadb.PersistentClient(
                path=self.persist_directory,
                settings=Settings(anonymized_telemetry=False)
            )
            logger.info(f"Initialized ChromaDB persistent client at {self.persist_directory}")
        else:
            # Ephemeral mode - in-memory only
            self.client = chromadb.Client(
                settings=Settings(anonymized_telemetry=False)
            )
            logger.info("Initialized ChromaDB ephemeral client (in-memory)")
        
        # Get or create collection
        try:
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"description": "FinRAG embeddings for RAPTOR tree nodes"}
            )
            logger.info(f"ChromaDB collection '{self.collection_name}' ready")
        except Exception as e:
            logger.error(f"Failed to create ChromaDB collection: {e}")
            raise
    
    # ---------------- Node management ----------------
    
    def add_nodes(self, nodes: List[ClusterNode]) -> None:
        """
        Add nodes to the vector store.
        
        Args:
            nodes: List of ClusterNode objects to add
        """
        for node in nodes:
            if node.node_id not in self.nodes:
                self.nodes[node.node_id] = node
                self.node_ids.append(node.node_id)
        
        logger.debug(f"Added {len(nodes)} nodes to ChromaVectorStore (total: {len(self.nodes)})")
    
    def add_vectors(
        self,
        node_ids: List[str],
        embeddings: np.ndarray,
        texts: Optional[List[str]] = None
    ) -> None:
        """
        Add vectors to ChromaDB.
        
        Args:
            node_ids: List of node IDs
            embeddings: numpy array of embeddings (n_nodes x dim)
            texts: Optional list of texts (defaults to node.text)
        """
        if embeddings.shape[0] != len(node_ids):
            raise ValueError(f"Embeddings shape {embeddings.shape[0]} doesn't match node_ids length {len(node_ids)}")
        
        # Convert numpy array to list of lists
        embeddings_list = embeddings.tolist()
        
        # Get texts from nodes if not provided
        if texts is None:
            texts = [self.nodes[node_id].text for node_id in node_ids if node_id in self.nodes]
        
        # Prepare metadata
        metadatas = []
        for node_id in node_ids:
            if node_id in self.nodes:
                node = self.nodes[node_id]
                metadatas.append({
                    "node_id": node_id,
                    "level": str(node.level),
                    "text_preview": node.text[:200] if len(node.text) > 200 else node.text
                })
            else:
                metadatas.append({"node_id": node_id, "level": "0"})
        
        # Add to ChromaDB
        try:
            self.collection.add(
                ids=node_ids,
                embeddings=embeddings_list,
                documents=texts,
                metadatas=metadatas
            )
            logger.info(f"Added {len(node_ids)} vectors to ChromaDB collection")
        except Exception as e:
            logger.error(f"Failed to add vectors to ChromaDB: {e}")
            raise
    
    def build_index(self) -> None:
        """
        Build the vector index.
        
        Note: ChromaDB builds index automatically on insert,
        so this is mainly for compatibility with PathwayVectorStore interface.
        """
        if not self.nodes:
            logger.warning("No nodes to index")
            return
        
        # Embed nodes if embeddings not already computed
        if self.embeddings is None:
            logger.info("Computing embeddings for nodes...")
            # This assumes embeddings are computed elsewhere and stored in embedding_cache
            # For now, we'll need to handle this in the caller
        
        self.is_built = True
        logger.info(f"ChromaDB index ready: {len(self.node_ids)} vectors")
    
    def search(
        self,
        query_embedding: np.ndarray,
        k: int = 10,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Tuple[str, float]]:
        """
        Search for similar vectors in ChromaDB.
        
        Args:
            query_embedding: Query embedding vector (1D numpy array)
            k: Number of results to return
            filter_dict: Optional metadata filter
            
        Returns:
            List of (node_id, score) tuples, sorted by relevance
        """
        # Check if collection has vectors (may be loaded from disk)
        try:
            collection_count = self.collection.count()
            if collection_count > 0:
                # Collection has data, even if is_built is False
                # This happens when loading from persisted ChromaDB
                if not self.is_built:
                    self.is_built = True
                    logger.debug("Marking ChromaDB as built (has persisted vectors)")
            elif not self.is_built or not self.node_ids:
                logger.warning("Index not built or empty")
                return []
        except Exception as e:
            logger.warning(f"Could not check ChromaDB collection count: {e}")
            if not self.is_built or not self.node_ids:
                return []
        
        # Convert query embedding to list
        query_embedding_list = query_embedding.tolist() if isinstance(query_embedding, np.ndarray) else query_embedding
        
        try:
            # Query ChromaDB
            results = self.collection.query(
                query_embeddings=[query_embedding_list],
                n_results=k,
                where=filter_dict  # Metadata filter
            )
            
            # Extract results
            if results["ids"] and len(results["ids"][0]) > 0:
                node_ids = results["ids"][0]
                distances = results["distances"][0]
                
                # ChromaDB returns distances (lower is better), convert to similarity scores
                # Assuming cosine distance, convert to similarity: 1 - distance
                similarities = [(1.0 - dist) if dist <= 1.0 else (1.0 / (1.0 + dist)) for dist in distances]
                
                return list(zip(node_ids, similarities))
            else:
                return []
                
        except Exception as e:
            logger.error(f"ChromaDB search failed: {e}")
            return []
    
    def clear(self) -> None:
        """Clear all vectors from ChromaDB."""
        try:
            self.client.delete_collection(name=self.collection_name)
            # Recreate empty collection
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"description": "FinRAG embeddings for RAPTOR tree nodes"}
            )
            self.nodes.clear()
            self.node_ids.clear()
            self.embeddings = None
            self.embedding_cache.clear()
            self.is_built = False
            logger.info("Cleared ChromaDB collection")
        except Exception as e:
            logger.error(f"Failed to clear ChromaDB collection: {e}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about the vector store."""
        try:
            count = self.collection.count()
            return {
                "total_vectors": count,
                "node_count": len(self.nodes),
                "collection_name": self.collection_name,
                "persist_directory": self.persist_directory,
                "is_built": self.is_built
            }
        except Exception as e:
            logger.error(f"Failed to get ChromaDB statistics: {e}")
            return {
                "total_vectors": 0,
                "node_count": len(self.nodes),
                "error": str(e)
            }
    
    # ---------------- Save/Load ----------------
    
    def save(self, path: str) -> None:
        """
        Save ChromaDB collection to disk.
        
        Args:
            path: Directory path to save ChromaDB data
        """
        if not self.persist_directory:
            logger.warning("Cannot save: ChromaDB is in ephemeral mode. Set persist_directory in config.")
            return
        
        save_path = Path(path)
        save_path.mkdir(parents=True, exist_ok=True)
        
        # Save metadata about the vector store
        metadata = {
            "collection_name": self.collection_name,
            "node_count": len(self.nodes),
            "node_ids": self.node_ids,
            "is_built": self.is_built
        }
        
        with open(save_path / "chroma_metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"ChromaDB metadata saved to {save_path}")
        logger.info(f"ChromaDB collection persisted at {self.persist_directory}")
    
    @classmethod
    def load(cls, path: str, config: Optional[ChromaConfig] = None) -> "ChromaVectorStore":
        """
        Load ChromaDB collection from disk.
        
        Args:
            path: Directory path containing ChromaDB data
            config: Optional ChromaConfig (if None, will try to load from path)
            
        Returns:
            Loaded ChromaVectorStore instance
        """
        if not CHROMADB_AVAILABLE:
            raise RuntimeError(
                f"ChromaDB not installed. Install with: pip install chromadb. "
                f"Error: {CHROMADB_ERROR}"
            )
        
        load_path = Path(path)
        
        # If config not provided, use path as persist_directory
        if config is None:
            config = ChromaConfig(persist_directory=str(load_path))
        elif not config.persist_directory:
            config.persist_directory = str(load_path)
        
        # Create instance (ChromaDB will load from persist_directory)
        store = cls(config=config)
        
        # Load metadata if available
        metadata_path = load_path / "chroma_metadata.json"
        if metadata_path.exists():
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                    store.is_built = metadata.get("is_built", False)
                    # Note: nodes and node_ids need to be loaded from tree.json separately
                    logger.info(f"Loaded ChromaDB metadata: {metadata.get('node_count', 0)} nodes")
            except Exception as e:
                logger.warning(f"Failed to load ChromaDB metadata: {e}")
        
        logger.info(f"Loaded ChromaDB collection from {load_path}")
        return store

