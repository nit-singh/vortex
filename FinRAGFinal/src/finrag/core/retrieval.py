"""
Retrieval mechanisms for RAPTOR tree traversal.
"""
from typing import List, Dict, Any, Tuple
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from .tree import RAPTORTree, ClusterNode
from .base_models import BaseEmbeddingModel


class RAPTORRetriever:
    """
    Implements retrieval strategies for the RAPTOR tree.
    """
    
    def __init__(
        self,
        tree: RAPTORTree,
        embedding_model: BaseEmbeddingModel,
        top_k: int = 10
    ):
        self.tree = tree
        self.embedding_model = embedding_model
        self.top_k = top_k
    
    def tree_traversal_retrieval(
        self,
        query: str,
        k: int = None
    ) -> List[Tuple[ClusterNode, float]]:
        """
        Retrieve nodes using tree traversal method.
        At each level, select top-k most similar nodes and expand them.
        
        Args:
            query: Query text
            k: Number of nodes to retrieve (default: self.top_k)
        
        Returns:
            List of (node, similarity_score) tuples
        """
        if k is None:
            k = self.top_k
        
        # Create query embedding
        query_embedding = self.embedding_model.create_embedding(query)
        
        # Start from root nodes
        current_nodes = self.tree.root_nodes
        retrieved_nodes = []
        
        # Traverse down the tree
        while current_nodes:
            # Calculate similarities
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
        """
        Retrieve nodes using collapsed tree method.
        Consider all nodes in the tree and return top-k most similar.
        
        Args:
            query: Query text
            k: Number of nodes to retrieve (default: self.top_k)
        
        Returns:
            List of (node, similarity_score) tuples
        """
        if k is None:
            k = self.top_k
        
        # Create query embedding
        query_embedding = self.embedding_model.create_embedding(query)
        
        # Get all nodes
        all_nodes = list(self.tree.all_nodes.values())
        node_embeddings = np.array([node.embedding for node in all_nodes])
        
        # Calculate similarities
        similarities = cosine_similarity([query_embedding], node_embeddings)[0]
        
        # Get top-k nodes
        top_indices = np.argsort(similarities)[-k:][::-1]
        retrieved_nodes = [(all_nodes[i], similarities[i]) for i in top_indices]
        
        return retrieved_nodes
    
    def retrieve(
        self,
        query: str,
        method: str = "tree_traversal",
        k: int = None
    ) -> List[Tuple[ClusterNode, float]]:
        """
        Retrieve relevant nodes using specified method.
        
        Args:
            query: Query text
            method: Retrieval method ("tree_traversal" or "collapsed_tree")
            k: Number of nodes to retrieve
        
        Returns:
            List of (node, similarity_score) tuples
        """
        if method == "tree_traversal":
            return self.tree_traversal_retrieval(query, k)
        elif method == "collapsed_tree":
            return self.collapsed_tree_retrieval(query, k)
        else:
            raise ValueError(f"Unknown retrieval method: {method}")
    
    def retrieve_with_context(
        self,
        query: str,
        method: str = "tree_traversal",
        k: int = None,
        include_children: bool = True
    ) -> str:
        """
        Retrieve relevant nodes and format as context string.
        
        Args:
            query: Query text
            method: Retrieval method
            k: Number of nodes to retrieve
            include_children: Whether to include children text
        
        Returns:
            Formatted context string
        """
        retrieved_nodes = self.retrieve(query, method, k)
        
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
