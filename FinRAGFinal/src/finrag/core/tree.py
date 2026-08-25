"""
RAPTOR Tree implementation for hierarchical document organization.
"""
import logging
from typing import List, Dict, Any, Optional
import numpy as np
from dataclasses import dataclass, asdict
import json
import pickle
from pathlib import Path

from .clustering import RAPTORClustering, ClusterNode
from .base_models import BaseEmbeddingModel, BaseSummarizationModel


logger = logging.getLogger(__name__)

# Import VectorStore implementations
try:
    from ..vectorstore import PathwayVectorStore, PathwayConfig
    PATHWAY_AVAILABLE = True
except ImportError:
    PATHWAY_AVAILABLE = False
    logger.warning("PathwayVectorStore not available. Dual storage disabled.")

# Import ChromaDB VectorStore
try:
    from ..vectorstore import ChromaVectorStore, ChromaConfig
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    ChromaVectorStore = None
    ChromaConfig = None
    logger.warning("ChromaVectorStore not available. Install with: pip install chromadb")

@dataclass
class TreeConfig:
    """Configuration for RAPTOR tree building."""
    max_depth: int = 4  # Set to 4 for fixed hierarchical structure
    max_cluster_size: int = 100
    min_cluster_size: int = 5
    reduction_dimension: int = 10
    summarization_length: int = 200


class RAPTORTree:    
    def __init__(
        self,
        embedding_model: BaseEmbeddingModel,
        summarization_model: BaseSummarizationModel,
        config: TreeConfig = None,
        use_metadata_clustering: bool = True,
        pathway_config: PathwayConfig = None,
        chroma_config: ChromaConfig = None,
        use_chromadb: bool = True  # Default to ChromaDB
    ):
        self.embedding_model = embedding_model
        self.summarization_model = summarization_model
        self.config = config or TreeConfig()
        self.use_metadata_clustering = use_metadata_clustering
        self.clustering = RAPTORClustering(
            max_cluster_size=self.config.max_cluster_size,
            min_cluster_size=self.config.min_cluster_size,
            reduction_dimension=self.config.reduction_dimension,
            use_metadata_clustering=use_metadata_clustering
        )
        
        self.root_nodes: List[ClusterNode] = []
        self.all_nodes: Dict[str, ClusterNode] = {}
        self.leaf_nodes: List[ClusterNode] = []
        
        # Initialize VectorStore (prefer ChromaDB, fallback to Pathway)
        self.pathway_config = pathway_config
        self.chroma_config = chroma_config
        self.use_chromadb = use_chromadb and CHROMADB_AVAILABLE
        self.vectorstore = None
        
        if self.use_chromadb and CHROMADB_AVAILABLE:
            # Use ChromaDB (default)
            if chroma_config is None:
                # Default config: persist to finrag_tree/chroma_vectorstore
                chroma_config = ChromaConfig(
                    collection_name="finrag_embeddings",
                    dimension=1536  # OpenAI embedding dimension
                )
            self.chroma_config = chroma_config
            self.vectorstore = ChromaVectorStore(chroma_config)
            logger.info("Vector storage enabled: JSON + ChromaDB VectorStore")
        elif pathway_config and PATHWAY_AVAILABLE:
            # Fallback to Pathway
            self.pathway_config = pathway_config
            self.vectorstore = PathwayVectorStore(pathway_config)
            logger.info("Vector storage enabled: JSON + Pathway VectorStore")
        else:
            logger.info("Vector storage disabled: using JSON only")
    
    def build_tree(
        self,
        chunks: List[Dict[str, Any]],
        chunk_embeddings: np.ndarray
    ) -> None:
        """Build RAPTOR tree from chunks and embeddings."""

        self.leaf_nodes = []
        for idx, (chunk, embedding) in enumerate(zip(chunks, chunk_embeddings)):
            node = ClusterNode(
                node_id=f"leaf_{idx}",
                text=chunk["text"],
                embedding=embedding,
                children=[],
                level=0,
                metadata=chunk
            )
            self.leaf_nodes.append(node)
            self.all_nodes[node.node_id] = node
        
        # Add leaf nodes to vectorstore
        if self.vectorstore:
            logger.info("Storing leaf nodes in Pathway VectorStore...")
            self.vectorstore.add_nodes(self.leaf_nodes)
        
        # Build tree recursively
        current_level_nodes = self.leaf_nodes
        current_level = 0
        
        logger.info("Level 0 (leaves): %d nodes", len(current_level_nodes))
        
        while current_level < self.config.max_depth and len(current_level_nodes) > 1:
            logger.info("Building level %d...", current_level + 1)
            next_level_nodes = self._build_level(
                current_level_nodes,
                current_level + 1
            )
            
            if len(next_level_nodes) == 0:
                break
            
            logger.info("Level %d: %d nodes", current_level + 1, len(next_level_nodes))
            current_level_nodes = next_level_nodes
            current_level += 1
        
        # Set root nodes
        self.root_nodes = current_level_nodes
        logger.info("Tree building complete! Total levels: %d", current_level + 1)
        
        # Build vectorstore index after all nodes are added
        if self.vectorstore:
            logger.info("Building Pathway VectorStore index...")
            self.vectorstore.build_index()
            logger.info("Pathway VectorStore ready for queries")
    
    def add_documents_incremental(
        self,
        new_chunks: List[Dict[str, Any]],
        new_embeddings: np.ndarray
    ) -> None:
        
        if not self.all_nodes:
            # No existing tree, do a full build
            logger.info("No existing tree found. Building from scratch...")
            return self.build_tree(new_chunks, new_embeddings)
        
        logger.info("Adding %d new chunks to existing tree incrementally...", len(new_chunks))
        
        # Create new leaf nodes
        new_leaf_nodes = []
        start_idx = len(self.leaf_nodes)
        
        for idx, (chunk, embedding) in enumerate(zip(new_chunks, new_embeddings)):
            node = ClusterNode(
                node_id=f"leaf_{start_idx + idx}",
                text=chunk["text"],
                embedding=embedding,
                children=[],
                level=0,
                metadata=chunk
            )
            new_leaf_nodes.append(node)
            self.all_nodes[node.node_id] = node
        
        # Add new leaves to existing leaves
        self.leaf_nodes.extend(new_leaf_nodes)
        
        # Add new leaf nodes to vectorstore
        if self.vectorstore:
            logger.info("Adding new leaf nodes to Pathway VectorStore...")
            self.vectorstore.add_nodes(new_leaf_nodes)
        
        # Remove old parent nodes from all_nodes (we'll rebuild them)
        old_parent_ids = [
            node_id for node_id, node in self.all_nodes.items()
            if node.level > 0
        ]
        for node_id in old_parent_ids:
            del self.all_nodes[node_id]
        
        logger.info("Rebuilding parent layers with updated leaf nodes...")
        
        # Rebuild tree from all leaves (old + new)
        current_level_nodes = self.leaf_nodes
        current_level = 0
        
        logger.info("Level 0 (leaves): %d nodes (added %d new)", 
                   len(current_level_nodes), len(new_leaf_nodes))
        
        while current_level < self.config.max_depth and len(current_level_nodes) > 1:
            logger.info("Rebuilding level %d...", current_level + 1)
            next_level_nodes = self._build_level(
                current_level_nodes,
                current_level + 1
            )
            
            if len(next_level_nodes) == 0:
                break
            
            logger.info("Level %d: %d nodes", current_level + 1, len(next_level_nodes))
            current_level_nodes = next_level_nodes
            current_level += 1
        
        # Update root nodes
        self.root_nodes = current_level_nodes
        
        logger.info("Incremental update complete! Total levels: %d", current_level + 1)
        logger.info("Total nodes now: %d (leaves: %d, parents: %d)",
                   len(self.all_nodes),
                   len(self.leaf_nodes),
                   len(self.all_nodes) - len(self.leaf_nodes))
        
        # Rebuild vectorstore index with all nodes
        if self.vectorstore:
            logger.info("Rebuilding Pathway VectorStore index...")
            self.vectorstore.build_index()
            logger.info("Pathway VectorStore ready for queries")
    
    def _inherit_metadata_from_children(
        self, 
        children: List[ClusterNode], 
        current_level: int
    ) -> Dict[str, Any]:
        """Inherit metadata from children nodes based on fixed hierarchy."""
        if not children:
            return {}
        
        from collections import Counter
        
        # Get the most common values from children
        sector_values = []
        company_values = []
        year_values = []
        
        for child in children:
            if hasattr(child, 'metadata') and child.metadata:
                sector = child.metadata.get('sector')
                company = child.metadata.get('company')
                year = child.metadata.get('year')
                
                if sector and sector != 'unknown' and sector != 'all':
                    sector_values.append(sector)
                if company and company != 'unknown' and company != 'all':
                    company_values.append(company)
                if year and year != 'unknown' and year != 'all':
                    year_values.append(year)
        
        # Determine metadata based on level
        inherited = {}
        
        if current_level == 1:
            # Level 1: Keep (Sector, Company, Year)
            if sector_values:
                inherited['sector'] = Counter(sector_values).most_common(1)[0][0]
            if company_values:
                inherited['company'] = Counter(company_values).most_common(1)[0][0]
            if year_values:
                inherited['year'] = Counter(year_values).most_common(1)[0][0]
                
        elif current_level == 2:
            # Level 2: Keep (Sector, Company, "all") - squash years
            if sector_values:
                inherited['sector'] = Counter(sector_values).most_common(1)[0][0]
            if company_values:
                inherited['company'] = Counter(company_values).most_common(1)[0][0]
            inherited['year'] = 'all'
            
        elif current_level == 3:
            # Level 3: Keep (Sector, "all", "all") - squash companies
            if sector_values:
                inherited['sector'] = Counter(sector_values).most_common(1)[0][0]
            inherited['company'] = 'all'
            inherited['year'] = 'all'
            
        else:  # Level 4+
            # Level 4: ("all", "all", "all") - final summary
            inherited['sector'] = 'all'
            inherited['company'] = 'all'
            inherited['year'] = 'all'
        
        return inherited
    
    def _build_level(
        self,
        nodes: List[ClusterNode],
        level: int
    ) -> List[ClusterNode]:
        """
        Build a single level of the tree.
        
        Args:
            nodes: Nodes from the previous level
            level: Current level number
        
        Returns:
            New nodes for this level
        """
        if len(nodes) <= self.config.min_cluster_size:
            return []
        
        # Get embeddings for current nodes
        embeddings = np.array([node.embedding for node in nodes])
        
        # Perform clustering with metadata awareness and current level
        clusters = self.clustering.perform_clustering_with_nodes(
            nodes, embeddings, current_level=level
        )
        
        if len(clusters) == 0:
            return []
        
        # Create parent nodes for each cluster
        new_nodes = []
        total_clusters = len(clusters)
        logger.info("  Creating %d cluster summaries...", total_clusters)
        
        for cluster_idx, cluster in enumerate(clusters):
            cluster_nodes = [nodes[i] for i in cluster]
            
            # Progress indicator
            if (cluster_idx + 1) % 5 == 0 or cluster_idx == total_clusters - 1:
                logger.info(
                    "  Progress: %d/%d clusters processed",
                    cluster_idx + 1,
                    total_clusters,
                )
            
            # Summarize cluster
            cluster_texts = [node.text for node in cluster_nodes]
            summary = self.summarization_model.summarize(
                cluster_texts,
                max_tokens=self.config.summarization_length
            )
            
            # Create embedding for summary
            summary_embedding = self.embedding_model.create_embedding(summary)
            
            # Inherit metadata from children with level-aware logic
            inherited_metadata = self._inherit_metadata_from_children(cluster_nodes, level)
            inherited_metadata.update({
                "num_children": len(cluster_nodes),
                "cluster_idx": cluster_idx
            })
            
            # Create new parent node
            parent_node = ClusterNode(
                node_id=f"level_{level}_cluster_{cluster_idx}",
                text=summary,
                embedding=summary_embedding,
                children=cluster_nodes,
                level=level,
                metadata=inherited_metadata
            )
            
            new_nodes.append(parent_node)
            self.all_nodes[parent_node.node_id] = parent_node
        
        # Add new level nodes to vectorstore
        if self.vectorstore and new_nodes:
            logger.info("  Storing level %d nodes in Pathway VectorStore...", level)
            self.vectorstore.add_nodes(new_nodes)
        
        return new_nodes
    
    def save(self, path: str) -> None:
        """
        Save the tree to disk with dual storage.
        
        Saves:
        1. JSON backup (always - primary format)
        2. Pickle (optional - faster but can fail)
        3. Pathway VectorStore (if configured)
        """
        save_path = Path(path)
        save_path.mkdir(parents=True, exist_ok=True)
        
        # Save tree structure
        tree_data = {
            "config": asdict(self.config),
            "root_node_ids": [node.node_id for node in self.root_nodes],
            "leaf_node_ids": [node.node_id for node in self.leaf_nodes],
            "use_metadata_clustering": self.use_metadata_clustering,
            "has_pathway_store": self.vectorstore is not None,
            "all_nodes": {}
        }
        
        # Serialize nodes
        for node_id, node in self.all_nodes.items():
            tree_data["all_nodes"][node_id] = {
                "node_id": node.node_id,
                "text": node.text,
                "embedding": node.embedding.tolist(),
                "children_ids": [child.node_id for child in node.children],
                "level": node.level,
                "metadata": node.metadata
            }
        
        # Save as JSON (primary format - always works)
        with open(save_path / "tree.json", "w") as f:
            json.dump(tree_data, f, indent=2)
        
        # Save VectorStore if configured (ChromaDB or Pathway)
        if self.vectorstore:
            if self.use_chromadb and isinstance(self.vectorstore, ChromaVectorStore):
                logger.info("  Saving ChromaDB VectorStore...")
                # Set persist directory if not already set
                if not self.chroma_config.persist_directory:
                    vectorstore_path = save_path / "chroma_vectorstore"
                    vectorstore_path.mkdir(parents=True, exist_ok=True)
                    self.chroma_config.persist_directory = str(vectorstore_path)
                    # Reinitialize with persist directory
                    old_nodes = list(self.vectorstore.nodes.values())
                    self.vectorstore = ChromaVectorStore(self.chroma_config)
                    # Re-add nodes
                    if old_nodes:
                        self.vectorstore.add_nodes(old_nodes)
                        # Add vectors if embeddings available
                        if self.vectorstore.embedding_cache:
                            node_ids = list(self.vectorstore.node_ids)
                            embeddings = np.array([self.vectorstore.embedding_cache[nid] for nid in node_ids])
                            texts = [self.vectorstore.nodes[nid].text for nid in node_ids]
                            self.vectorstore.add_vectors(node_ids, embeddings, texts)
                            self.vectorstore.build_index()
                else:
                    vectorstore_path = Path(self.chroma_config.persist_directory)
                self.vectorstore.save(str(vectorstore_path))
                logger.info("  ChromaDB VectorStore saved")
            elif isinstance(self.vectorstore, PathwayVectorStore):
                logger.info("  Saving Pathway VectorStore...")
                vectorstore_path = save_path / "pathway_vectorstore"
                self.vectorstore.save(str(vectorstore_path))
                logger.info("  Pathway VectorStore saved")
        
        # Try to save as pickle (faster to load but can fail with threading objects)
        try:
            # Store models temporarily
            temp_embedding = self.embedding_model
            temp_summarization = self.summarization_model
            temp_vectorstore = self.vectorstore
            
            # Remove unpicklable models
            self.embedding_model = None
            self.summarization_model = None
            self.vectorstore = None
            
            with open(save_path / "tree.pkl", "wb") as f:
                pickle.dump(self, f)
            
            # Restore models
            self.embedding_model = temp_embedding
            self.summarization_model = temp_summarization
            self.vectorstore = temp_vectorstore
            
            logger.info("  Saved as JSON + pickle + Pathway" if self.vectorstore else "  Saved as JSON + pickle")
        except Exception as e:
            # Restore models if pickle failed
            self.embedding_model = temp_embedding
            self.summarization_model = temp_summarization
            self.vectorstore = temp_vectorstore
            logger.warning("  Pickle save failed (%s), using JSON only", str(e))
            logger.info("  Tree saved as JSON + Pathway" if self.vectorstore else "  Tree saved as JSON")
    
    @classmethod
    def load(cls, path: str, embedding_model: BaseEmbeddingModel, 
             summarization_model: BaseSummarizationModel,
             pathway_config: PathwayConfig = None,
             chroma_config: ChromaConfig = None,
             use_chromadb: bool = True) -> 'RAPTORTree':
        """
        Load a tree from disk with dual storage support.
        
        Loads from:
        1. Pickle (fastest, if available)
        2. JSON backup (always available)
        3. Pathway VectorStore (if was saved with it)
        
        Args:
            path: Directory path to load from
            embedding_model: Embedding model to use
            summarization_model: Summarization model to use
            pathway_config: Optional Pathway configuration for loading vectorstore
        """
        load_path = Path(path)
        
        # Try pickle first (fastest) - but may not exist if save failed
        pkl_path = load_path / "tree.pkl"
        if pkl_path.exists():
            try:
                with open(pkl_path, "rb") as f:
                    tree = pickle.load(f)
                    tree.embedding_model = embedding_model
                    tree.summarization_model = summarization_model
                    
                # Load VectorStore if it was saved (ChromaDB or Pathway)
                chroma_vectorstore_path = load_path / "chroma_vectorstore"
                pathway_vectorstore_path = load_path / "pathway_vectorstore"
                
                if use_chromadb and CHROMADB_AVAILABLE and chroma_vectorstore_path.exists():
                    logger.info("  Loading ChromaDB VectorStore...")
                    if chroma_config is None:
                        chroma_config = ChromaConfig(persist_directory=str(chroma_vectorstore_path))
                    tree.vectorstore = ChromaVectorStore.load(str(chroma_vectorstore_path), chroma_config)
                    tree.chroma_config = chroma_config
                    tree.use_chromadb = True
                    # Re-populate nodes and mark as built
                    if tree.all_nodes:
                        all_nodes_list = list(tree.all_nodes.values())
                        tree.vectorstore.add_nodes(all_nodes_list)
                        # Populate embedding cache
                        for node_id, node in tree.all_nodes.items():
                            tree.vectorstore.embedding_cache[node_id] = node.embedding
                        tree.vectorstore.is_built = True
                    logger.info("  Loaded from pickle + ChromaDB (fast)")
                elif pathway_vectorstore_path.exists() and pathway_config and PATHWAY_AVAILABLE:
                    logger.info("  Loading Pathway VectorStore...")
                    tree.vectorstore = PathwayVectorStore.load(str(pathway_vectorstore_path))
                    tree.pathway_config = pathway_config
                    tree.use_chromadb = False
                    logger.info("  Loaded from pickle + Pathway (fast)")
                else:
                    logger.info("  Loaded from pickle (fast)")
                
                return tree
            except Exception as e:
                logger.warning("  Pickle load failed (%s), trying JSON...", str(e))
        
        # Fall back to JSON (always works)
        json_path = load_path / "tree.json"
        if not json_path.exists():
            raise FileNotFoundError(f"No tree found at {path}. Expected tree.json or tree.pkl")
        
        with open(json_path, "r") as f:
            tree_data = json.load(f)
        
        # Reconstruct tree
        config = TreeConfig(**tree_data["config"])
        use_metadata_clustering = tree_data.get("use_metadata_clustering", False)
        has_chromadb = tree_data.get("has_chromadb_store", False) or tree_data.get("use_chromadb", True)
        
        # Initialize with appropriate vectorstore config
        if has_chromadb and use_chromadb and CHROMADB_AVAILABLE:
            if chroma_config is None:
                chroma_vectorstore_path = load_path / "chroma_vectorstore"
                chroma_config = ChromaConfig(persist_directory=str(chroma_vectorstore_path))
            tree = cls(embedding_model, summarization_model, config, use_metadata_clustering, 
                      pathway_config=None, chroma_config=chroma_config, use_chromadb=True)
        else:
            tree = cls(embedding_model, summarization_model, config, use_metadata_clustering, 
                      pathway_config=pathway_config, chroma_config=None, use_chromadb=False)
        
        # Rebuild nodes
        all_nodes = {}
        for node_id, node_data in tree_data["all_nodes"].items():
            node = ClusterNode(
                node_id=node_data["node_id"],
                text=node_data["text"],
                embedding=np.array(node_data["embedding"]),
                children=[],  # Will be filled later
                level=node_data["level"],
                metadata=node_data["metadata"]
            )
            all_nodes[node_id] = node
        
        # Rebuild parent-child relationships
        for node_id, node_data in tree_data["all_nodes"].items():
            node = all_nodes[node_id]
            node.children = [all_nodes[child_id] for child_id in node_data["children_ids"]]
        
        tree.all_nodes = all_nodes
        tree.root_nodes = [all_nodes[node_id] for node_id in tree_data["root_node_ids"]]
        tree.leaf_nodes = [all_nodes[node_id] for node_id in tree_data["leaf_node_ids"]]
        
        # Load VectorStore if it was saved (ChromaDB or Pathway)
        chroma_vectorstore_path = load_path / "chroma_vectorstore"
        pathway_vectorstore_path = load_path / "pathway_vectorstore"
        has_pathway_store = tree_data.get("has_pathway_store", False)
        has_chromadb_store = tree_data.get("has_chromadb_store", False) or tree_data.get("use_chromadb", False)
        
        if has_chromadb_store and chroma_vectorstore_path.exists() and use_chromadb and CHROMADB_AVAILABLE:
            logger.info("  Loading ChromaDB VectorStore...")
            if chroma_config is None:
                chroma_config = ChromaConfig(persist_directory=str(chroma_vectorstore_path))
            tree.vectorstore = ChromaVectorStore.load(str(chroma_vectorstore_path), chroma_config)
            tree.chroma_config = chroma_config
            tree.use_chromadb = True
            # Re-add nodes to vectorstore from tree
            if tree.leaf_nodes:
                tree.vectorstore.add_nodes(tree.leaf_nodes)
                # Add embeddings to cache and vectors to ChromaDB
                node_ids = [node.node_id for node in tree.leaf_nodes]
                embeddings = np.array([node.embedding for node in tree.leaf_nodes])
                texts = [node.text for node in tree.leaf_nodes]
                for node_id, emb, text in zip(node_ids, embeddings, texts):
                    tree.vectorstore.embedding_cache[node_id] = emb
                tree.vectorstore.add_vectors(node_ids, embeddings, texts)
                tree.vectorstore.build_index()
            logger.info("  Loaded from JSON + ChromaDB")
        elif has_pathway_store and pathway_vectorstore_path.exists() and pathway_config and PATHWAY_AVAILABLE:
            logger.info("  Loading Pathway VectorStore...")
            tree.vectorstore = PathwayVectorStore.load(str(pathway_vectorstore_path))
            tree.pathway_config = pathway_config
            tree.use_chromadb = False
            logger.info("  Loaded from JSON + Pathway")
        else:
            logger.info("  Loaded from JSON")
        
        return tree
    
    def get_all_texts(self) -> List[str]:
        """Get all texts in the tree."""
        return [node.text for node in self.all_nodes.values()]
    
    def get_all_embeddings(self) -> np.ndarray:
        """Get all embeddings in the tree."""
        return np.array([node.embedding for node in self.all_nodes.values()])
    
    def get_node_by_id(self, node_id: str) -> Optional[ClusterNode]:
        """Get a node by its ID."""
        return self.all_nodes.get(node_id)
