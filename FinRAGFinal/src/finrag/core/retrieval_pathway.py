"""Enhanced retrieval with Pathway and ChromaDB vector store and hybrid search support."""
import logging
from typing import List, Dict, Any, Tuple, Optional
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import re
from collections import Counter
import math

from .tree import RAPTORTree, ClusterNode
from .base_models import BaseEmbeddingModel
from ..vectorstore import PathwayVectorStore, PathwayConfig

logger = logging.getLogger(__name__)


class BM25:
    """BM25 implementation for keyword-based retrieval."""
    
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_freqs: Dict[str, int] = {}
        self.doc_lengths: List[int] = []
        self.avg_doc_length: float = 0.0
        self.corpus_size: int = 0
        self.documents: List[List[str]] = []
    
    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text: lowercase and split on non-alphanumeric."""
        text = text.lower()
        tokens = re.findall(r'\b[a-z0-9]+\b', text)
        # Remove common stopwords
        stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
                     'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
                     'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
                     'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
                     'it', 'its', 'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she',
                     'we', 'they', 'what', 'which', 'who', 'whom', 'where', 'when', 'why', 'how'}
        return [t for t in tokens if t not in stopwords and len(t) > 2]
    
    def fit(self, documents: List[str]) -> None:
        """Fit BM25 on a corpus of documents."""
        self.documents = [self._tokenize(doc) for doc in documents]
        self.corpus_size = len(self.documents)
        self.doc_lengths = [len(doc) for doc in self.documents]
        self.avg_doc_length = sum(self.doc_lengths) / max(self.corpus_size, 1)
        
        # Calculate document frequencies
        self.doc_freqs = {}
        for doc in self.documents:
            unique_terms = set(doc)
            for term in unique_terms:
                self.doc_freqs[term] = self.doc_freqs.get(term, 0) + 1
    
    def _idf(self, term: str) -> float:
        """Calculate inverse document frequency."""
        df = self.doc_freqs.get(term, 0)
        return math.log((self.corpus_size - df + 0.5) / (df + 0.5) + 1)
    
    def score(self, query: str, doc_idx: int) -> float:
        """Score a document against a query."""
        query_terms = self._tokenize(query)
        doc = self.documents[doc_idx]
        doc_len = self.doc_lengths[doc_idx]
        
        score = 0.0
        term_freqs = Counter(doc)
        
        for term in query_terms:
            if term not in term_freqs:
                continue
            
            tf = term_freqs[term]
            idf = self._idf(term)
            
            # BM25 formula
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * (doc_len / self.avg_doc_length))
            score += idf * (numerator / denominator)
        
        return score
    
    def search(self, query: str, k: int = 10) -> List[Tuple[int, float]]:
        """Search for top-k documents matching the query."""
        scores = [(i, self.score(query, i)) for i in range(self.corpus_size)]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:k]


class RAPTORRetriever:
    """Retrieval strategies for the RAPTOR tree with Pathway vector store support."""
    
    def __init__(
        self,
        tree: RAPTORTree,
        embedding_model: BaseEmbeddingModel,
        top_k: int = 50,  # Increased from 10 to 50
        use_pathway: bool = False,
        pathway_config: PathwayConfig = None,
        use_hybrid: bool = True,  # Enable hybrid search by default
        hybrid_alpha: float = 0.7  # Weight for semantic vs BM25 (0.7 = 70% semantic, 30% BM25)
    ):
        self.tree = tree
        self.embedding_model = embedding_model
        self.top_k = top_k
        self.use_pathway = use_pathway
        self.use_hybrid = use_hybrid
        self.hybrid_alpha = hybrid_alpha
        
        # BM25 index for keyword matching
        self.bm25: Optional[BM25] = None
        self.node_id_list: List[str] = []  # Maps BM25 doc index to node_id
        
        # Use existing vector store from tree if available (ChromaDB or Pathway)
        self.vector_store = None
        self.use_chromadb = False
        
        # Check if tree has a vectorstore (ChromaDB or Pathway)
        if hasattr(tree, 'vectorstore') and tree.vectorstore is not None:
            self.vector_store = tree.vectorstore
            # Detect if it's ChromaDB
            from ..vectorstore.chroma_store import ChromaVectorStore
            if isinstance(tree.vectorstore, ChromaVectorStore):
                self.use_chromadb = True
                self.use_pathway = False
                logger.info("Using ChromaDB vectorstore from tree")
            else:
                self.use_pathway = True
                logger.info("Using Pathway vectorstore from tree")
        elif use_pathway:
            # Create new Pathway vectorstore
            print("Initializing new PathwayVectorStore...")
            self.vector_store = PathwayVectorStore(pathway_config or PathwayConfig())
            if tree.all_nodes:
                self._initialize_vector_store()
        
        # Initialize BM25 index if hybrid search enabled
        if use_hybrid and tree.all_nodes:
            self._initialize_bm25()
    
    def _initialize_vector_store(self) -> None:
        """Initialize Pathway vector store with tree nodes."""
        nodes = list(self.tree.all_nodes.values())
        self.vector_store.add_nodes(nodes)
        self.vector_store.build_index()
    
    def _initialize_bm25(self) -> None:
        """Initialize BM25 index for keyword matching."""
        self.node_id_list = list(self.tree.all_nodes.keys())
        documents = [self.tree.all_nodes[nid].text for nid in self.node_id_list]
        self.bm25 = BM25()
        self.bm25.fit(documents)
    
    def hybrid_retrieval(
        self,
        query: str,
        k: int = None,
        alpha: float = None
    ) -> List[Tuple[ClusterNode, float]]:
        """Hybrid retrieval combining semantic similarity and BM25 keyword matching."""
        if k is None:
            k = self.top_k
        if alpha is None:
            alpha = self.hybrid_alpha
        
        # Get semantic results (retrieve more to ensure good fusion)
        semantic_k = min(k * 2, len(self.tree.all_nodes))
        semantic_results = self.collapsed_tree_retrieval(query, k=semantic_k)
        
        # Get BM25 results
        bm25_results = []
        if self.bm25 is not None:
            bm25_scores = self.bm25.search(query, k=semantic_k)
            for doc_idx, score in bm25_scores:
                node_id = self.node_id_list[doc_idx]
                node = self.tree.all_nodes[node_id]
                bm25_results.append((node, score))
        
        # Normalize scores to [0, 1] range
        def normalize_scores(results: List[Tuple[ClusterNode, float]]) -> Dict[str, float]:
            if not results:
                return {}
            scores = [s for _, s in results]
            min_s, max_s = min(scores), max(scores)
            range_s = max_s - min_s if max_s > min_s else 1.0
            return {node.node_id: (score - min_s) / range_s for node, score in results}
        
        semantic_norm = normalize_scores(semantic_results)
        bm25_norm = normalize_scores(bm25_results)
        
        # Combine scores using weighted fusion
        all_node_ids = set(semantic_norm.keys()) | set(bm25_norm.keys())
        combined_scores: Dict[str, float] = {}
        
        for node_id in all_node_ids:
            sem_score = semantic_norm.get(node_id, 0.0)
            bm25_score = bm25_norm.get(node_id, 0.0)
            combined_scores[node_id] = alpha * sem_score + (1 - alpha) * bm25_score
        
        # Sort by combined score and return top-k
        sorted_nodes = sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)
        results = []
        for node_id, score in sorted_nodes[:k]:
            node = self.tree.all_nodes[node_id]
            results.append((node, score))
        
        return results

    def tree_traversal_retrieval(
        self,
        query: str,
        k: int = None
    ) -> List[Tuple[ClusterNode, float]]:
        """Retrieve nodes using tree traversal method."""
        if k is None:
            k = self.top_k
        
        # Create query embedding
        query_embedding = self.embedding_model.create_embedding(query)
        
        # Start from root nodes
        current_nodes = self.tree.root_nodes
        retrieved_nodes = []
        
        # Traverse down the tree
        while current_nodes:
            if self.use_pathway and self.vector_store:
                # Use Pathway vector store with level filtering for efficient ANN search
                current_level = current_nodes[0].level if current_nodes else 0
                
                # Search using Pathway's ANN index filtered by level
                level_results = self.vector_store.search(
                    query_embedding=query_embedding,
                    k=k,
                    filter_level=current_level
                )
                
                # Get top-k nodes from level results
                top_nodes = level_results[:k]
            else:
                # Fallback: numpy-based approach for non-Pathway mode
                node_embeddings = np.array([node.embedding for node in current_nodes])
                similarities = cosine_similarity([query_embedding], node_embeddings)[0]
                
                # Get top-k nodes at this level
                top_indices = np.argsort(similarities)[-k:][::-1]
                top_nodes = [(current_nodes[i], similarities[i]) for i in top_indices]
            
            # Add to retrieved nodes
            retrieved_nodes.extend(top_nodes)
            
            # Expand to children
            next_level_nodes = []
            for node, _ in top_nodes:
                next_level_nodes.extend(node.children)
            
            current_nodes = next_level_nodes
        
        # Sort by similarity and return top-k overall
        retrieved_nodes.sort(key=lambda x: x[1], reverse=True)
        return retrieved_nodes[:k]
    
    def collapsed_tree_retrieval(
        self,
        query: str,
        k: int = None
    ) -> List[Tuple[ClusterNode, float]]:
        """Retrieve all nodes and return top-k most similar."""
        if k is None:
            k = self.top_k
        
        # Create query embedding
        query_embedding = self.embedding_model.create_embedding(query)
        
        if self.vector_store:
            # Use vector store (ChromaDB or Pathway) for similarity search
            if self.use_chromadb:
                # ChromaDB returns (node_id, score) tuples
                results = self.vector_store.search(query_embedding, k=k)
                # Convert to (node, score) tuples
                retrieved_nodes = [
                    (self.tree.all_nodes[node_id], score) 
                    for node_id, score in results 
                    if node_id in self.tree.all_nodes
                ]
            else:
                # Pathway vector store
                retrieved_nodes = self.vector_store.search(query_embedding, k=k)
        else:
            # Original numpy-based approach
            all_nodes = list(self.tree.all_nodes.values())
            node_embeddings = np.array([node.embedding for node in all_nodes])
            
            # Calculate similarities
            similarities = cosine_similarity([query_embedding], node_embeddings)[0]
            
            # Get top-k nodes
            top_indices = np.argsort(similarities)[-k:][::-1]
            retrieved_nodes = [(all_nodes[i], similarities[i]) for i in top_indices]
        
        return retrieved_nodes
    
    def metadata_filtered_retrieval(
        self,
        query: str,
        metadata_filters: Dict[str, Any],
        k: int = None
    ) -> List[Tuple[ClusterNode, float]]:
        """Retrieve nodes with metadata filtering."""
        if k is None:
            k = self.top_k
        
        # Create query embedding
        query_embedding = self.embedding_model.create_embedding(query)
        
        if self.use_pathway and self.vector_store:
            # Use Pathway vector store with filters
            retrieved_nodes = self.vector_store.search(
                query_embedding,
                k=k,
                filter_metadata=metadata_filters
            )
        else:
            # Filter nodes by metadata
            filtered_nodes = []
            for node in self.tree.all_nodes.values():
                match = True
                for key, value in metadata_filters.items():
                    if node.metadata.get(key) != value:
                        match = False
                        break
                if match:
                    filtered_nodes.append(node)
            
            if not filtered_nodes:
                return []
            
            # Calculate similarities
            node_embeddings = np.array([node.embedding for node in filtered_nodes])
            similarities = cosine_similarity([query_embedding], node_embeddings)[0]
            
            # Get top-k
            top_k = min(k, len(filtered_nodes))
            top_indices = np.argsort(similarities)[-top_k:][::-1]
            retrieved_nodes = [(filtered_nodes[i], similarities[i]) for i in top_indices]
        
        return retrieved_nodes
    
    def retrieve(
        self,
        query: str,
        method: str = "hybrid",
        k: int = None,
        metadata_filters: Optional[Dict[str, Any]] = None
    ) -> List[Tuple[ClusterNode, float]]:
        """Retrieve relevant nodes using specified method."""
        if method == "hybrid":
            # Use hybrid search if BM25 is initialized, otherwise fall back to collapsed_tree
            if self.use_hybrid and self.bm25 is not None:
                return self.hybrid_retrieval(query, k)
            else:
                return self.collapsed_tree_retrieval(query, k)
        elif method == "tree_traversal":
            return self.tree_traversal_retrieval(query, k)
        elif method == "collapsed_tree":
            return self.collapsed_tree_retrieval(query, k)
        elif method == "metadata_filtered":
            if not metadata_filters:
                raise ValueError("metadata_filters required for metadata_filtered method")
            return self.metadata_filtered_retrieval(query, metadata_filters, k)
        else:
            raise ValueError(f"Unknown retrieval method: {method}")
    
    def retrieve_with_context(
        self,
        query: str,
        method: str = "tree_traversal",
        k: int = None,
        include_children: bool = True,
        metadata_filters: Optional[Dict[str, Any]] = None
    ) -> str:
        """Retrieve relevant nodes and format as context string."""
        retrieved_nodes = self.retrieve(query, method, k, metadata_filters)
        
        context_parts = []
        for idx, (node, score) in enumerate(retrieved_nodes):
            context_parts.append(f"[Document {idx+1}] (Relevance: {score:.3f})")
            context_parts.append(node.text)
            
            # Add children text if requested and node has children
            if include_children and node.children:
                for child_idx, child in enumerate(node.children[:3]):  # Limit to 3 children
                    context_parts.append(f"  [Sub-document {idx+1}.{child_idx+1}]")
                    context_parts.append(f"  {child.text}")
            
            context_parts.append("")  # Empty line between documents
        
        return "\n".join(context_parts)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get retrieval statistics."""
        stats = {
            "top_k": self.top_k,
            "use_pathway": self.use_pathway,
            "use_hybrid": self.use_hybrid,
            "hybrid_alpha": self.hybrid_alpha,
            "bm25_initialized": self.bm25 is not None,
            "total_nodes": len(self.tree.all_nodes)
        }
        
        if self.use_pathway and self.vector_store:
            stats["vector_store"] = self.vector_store.get_statistics()
        
        if self.bm25 is not None:
            stats["bm25_vocab_size"] = len(self.bm25.doc_freqs)
        
        return stats
