"""
RAPTOR-style clustering implementation for FinRAG.
"""
import logging
from typing import List, Dict, Any, Optional
import numpy as np
from sklearn.cluster import DBSCAN, KMeans
from sklearn.mixture import GaussianMixture
import umap
from dataclasses import dataclass


logger = logging.getLogger(__name__)


@dataclass
class ClusterNode:
    """Node in the RAPTOR tree."""
    node_id: str
    text: str
    embedding: np.ndarray
    children: List['ClusterNode']
    level: int
    metadata: Dict[str, Any]


class RAPTORClustering:
    """RAPTOR clustering algorithm with metadata support."""
    
    def __init__(
        self,
        max_cluster_size: int = 100,
        min_cluster_size: int = 5,
        reduction_dimension: int = 10,
        clustering_algorithm: str = "gaussian_mixture",
        use_metadata_clustering: bool = True,
        metadata_keys: List[str] = None
    ):
        self.max_cluster_size = max_cluster_size
        self.min_cluster_size = min_cluster_size
        self.reduction_dimension = reduction_dimension
        self.clustering_algorithm = clustering_algorithm
        self.use_metadata_clustering = use_metadata_clustering
        self.metadata_keys = metadata_keys or ["sector", "company", "year"]
    
    def global_cluster_embeddings(
        self,
        embeddings: np.ndarray,
        dim: int = None,
        n_neighbors: Optional[int] = None,
        metric: str = "cosine"
    ) -> np.ndarray:
        """Perform global dimensionality reduction using UMAP."""
        if dim is None:
            dim = self.reduction_dimension
        
        if n_neighbors is None:
            n_neighbors = int((len(embeddings) - 1) ** 0.5)
        
        reducer = umap.UMAP(
            n_neighbors=n_neighbors,
            n_components=min(dim, len(embeddings) - 2),
            metric=metric,
            random_state=42
        )
        
        return reducer.fit_transform(embeddings)
    
    def local_cluster_embeddings(
        self,
        embeddings: np.ndarray,
        dim: int = None,
        num_neighbors: int = 10,
        metric: str = "cosine"
    ) -> np.ndarray:
        """Perform local dimensionality reduction using UMAP."""
        if dim is None:
            dim = self.reduction_dimension
        
        reducer = umap.UMAP(
            n_neighbors=num_neighbors,
            n_components=min(dim, len(embeddings) - 2),
            metric=metric,
            random_state=42
        )
        
        return reducer.fit_transform(embeddings)
    
    def get_optimal_clusters(
        self,
        embeddings: np.ndarray,
        max_clusters: int = 50,
        random_state: int = 42
    ) -> int:
        """Determine optimal number of clusters using BIC."""
        max_clusters = min(max_clusters, len(embeddings))
        n_clusters = np.arange(1, max_clusters)
        bics = []
        
        for n in n_clusters:
            gm = GaussianMixture(n_components=n, random_state=random_state)
            gm.fit(embeddings)
            bics.append(gm.bic(embeddings))
        
        # Find elbow point
        optimal_clusters = n_clusters[np.argmin(bics)]
        return optimal_clusters
    
    def gmm_clustering(
        self,
        embeddings: np.ndarray,
        threshold: float = 0.5,
        random_state: int = 42
    ) -> List[np.ndarray]:
        """Perform Gaussian Mixture Model clustering."""
        n_clusters = self.get_optimal_clusters(embeddings)
        gm = GaussianMixture(n_components=n_clusters, random_state=random_state)
        gm.fit(embeddings)
        
        probs = gm.predict_proba(embeddings)
        labels = [np.where(prob > threshold)[0] for prob in probs]
        
        # Group by cluster
        clusters = [[] for _ in range(n_clusters)]
        for idx, label_list in enumerate(labels):
            for label in label_list:
                clusters[label].append(idx)
        
        # Filter out empty clusters and convert to numpy arrays
        clusters = [np.array(cluster) for cluster in clusters if len(cluster) > 0]
        
        return clusters
    
    def perform_clustering(
        self,
        embeddings: np.ndarray,
        dim: int = 10,
        threshold: float = 0.5
    ) -> List[np.ndarray]:
        """Perform full clustering pipeline: reduction + clustering."""
        if len(embeddings) <= self.min_cluster_size:
            # Don't cluster if too few items
            return [np.arange(len(embeddings))]
        
        # Reduce dimensionality
        reduced_embeddings = self.global_cluster_embeddings(embeddings, dim=dim)
        
        # Perform clustering
        if self.clustering_algorithm == "gaussian_mixture":
            clusters = self.gmm_clustering(reduced_embeddings, threshold=threshold)
        elif self.clustering_algorithm == "kmeans":
            n_clusters = min(len(embeddings) // self.min_cluster_size, 10)
            kmeans = KMeans(n_clusters=n_clusters, random_state=42)
            labels = kmeans.fit_predict(reduced_embeddings)
            clusters = [np.where(labels == i)[0] for i in range(n_clusters)]
        else:
            raise ValueError(f"Unknown clustering algorithm: {self.clustering_algorithm}")
        
        # Filter clusters by size
        clusters = [
            cluster for cluster in clusters 
            if len(cluster) >= self.min_cluster_size
        ]
        
        return clusters
    
    def extract_metadata_groups(
        self,
        nodes: List,
        metadata_keys: List[str] = None
    ) -> Dict[tuple, List[int]]:
        """
        Group nodes by metadata (sector, company, year) as per FinRAG paper.
        
        Args:
            nodes: List of nodes with metadata
            metadata_keys: Keys to use for grouping (default: self.metadata_keys)
        
        Returns:
            Dictionary mapping metadata tuples to lists of node indices
        """
        if metadata_keys is None:
            metadata_keys = self.metadata_keys
        
        metadata_groups = {}
        
        for idx, node in enumerate(nodes):
            # Extract metadata values
            metadata_values = []
            for key in metadata_keys:
                value = node.metadata.get(key, "unknown")
                # Normalize the value
                if value is None:
                    value = "unknown"
                elif isinstance(value, (int, float)):
                    value = str(value)
                elif not isinstance(value, str):
                    value = str(value)
                metadata_values.append(value.lower().strip())
            
            # Create metadata tuple as key
            metadata_key = tuple(metadata_values)
            
            if metadata_key not in metadata_groups:
                metadata_groups[metadata_key] = []
            metadata_groups[metadata_key].append(idx)
        
        return metadata_groups
    
    def perform_metadata_clustering(
        self,
        nodes: List,
        embeddings: np.ndarray,
        dim: int = 10,
        threshold: float = 0.5
    ) -> List[np.ndarray]:
        """
        Perform clustering with metadata grouping (sector, company, year) as first step.
        Then perform embedding-based clustering within each metadata group.
        
        Args:
            nodes: List of nodes with metadata
            embeddings: Embeddings for the nodes
            dim: Dimension for reduction
            threshold: Clustering threshold
        
        Returns:
            List of clusters (each cluster is an array of indices)
        """
        if len(embeddings) <= self.min_cluster_size:
            return [np.arange(len(embeddings))]
        
        # Step 1: Group by metadata
        metadata_groups = self.extract_metadata_groups(nodes)
        
        logger.info("  Metadata grouping: %d groups found", len(metadata_groups))
        for metadata_key, indices in list(metadata_groups.items())[:3]:
            logger.info("    %s: %d nodes", metadata_key, len(indices))
        
        all_clusters = []
        
        # Step 2: Perform embedding-based clustering within each metadata group
        for metadata_key, group_indices in metadata_groups.items():
            group_indices = np.array(group_indices)
            
            # If group is too small, treat it as a single cluster
            if len(group_indices) <= self.min_cluster_size:
                all_clusters.append(group_indices)
                continue
            
            # If group is too large, perform sub-clustering
            if len(group_indices) > self.max_cluster_size:
                # Get embeddings for this group
                group_embeddings = embeddings[group_indices]
                
                # Perform embedding-based clustering
                reduced = self.global_cluster_embeddings(group_embeddings, dim=dim)
                
                if self.clustering_algorithm == "gaussian_mixture":
                    sub_clusters = self.gmm_clustering(reduced, threshold=threshold)
                elif self.clustering_algorithm == "kmeans":
                    n_clusters = min(len(group_indices) // self.min_cluster_size, 10)
                    kmeans = KMeans(n_clusters=n_clusters, random_state=42)
                    labels = kmeans.fit_predict(reduced)
                    sub_clusters = [np.where(labels == i)[0] for i in range(n_clusters)]
                else:
                    sub_clusters = [np.arange(len(group_indices))]
                
                # Map back to original indices
                for sub_cluster in sub_clusters:
                    if len(sub_cluster) >= self.min_cluster_size:
                        all_clusters.append(group_indices[sub_cluster])
            else:
                # Group size is acceptable, keep as single cluster
                all_clusters.append(group_indices)
        
        return all_clusters
    
    def perform_fixed_hierarchical_clustering(
        self,
        nodes: List,
        embeddings: np.ndarray,
        current_level: int,
        dim: int = 10,
        threshold: float = 0.5
    ) -> List[np.ndarray]:
        """
        Perform fixed hierarchical clustering based on metadata levels:
        - Level 1: Group by (Sector, Company, Year) - squash years
        - Level 2: Group by (Sector, Company) - squash companies
        - Level 3: Group by (Sector) - squash sectors
        - Level 4: Group all - final summary
        
        Args:
            nodes: List of nodes with metadata
            embeddings: Embeddings for the nodes
            current_level: Current level being built (1-4)
            dim: Dimension for reduction
            threshold: Clustering threshold
        
        Returns:
            List of clusters (each cluster is an array of indices)
        """
        if len(embeddings) <= self.min_cluster_size:
            return [np.arange(len(embeddings))]
        
        # Define grouping keys for each level
        level_grouping = {
            1: ["sector", "company", "year"],  # Layer 1: squash years
            2: ["sector", "company"],          # Layer 2: squash companies  
            3: ["sector"],                     # Layer 3: squash sectors
            4: []                              # Layer 4: squash all (final summary)
        }
        
        grouping_keys = level_grouping.get(current_level, [])
        
        # If level 4 or no grouping keys, cluster everything together
        if current_level >= 4 or not grouping_keys:
            # Create a single cluster of all nodes
            return [np.arange(len(embeddings))]
        
        # Group by the specified metadata keys
        metadata_groups = {}
        for idx, node in enumerate(nodes):
            # Extract metadata values for grouping
            metadata_values = []
            for key in grouping_keys:
                value = node.metadata.get(key, "unknown")
                # Normalize the value
                if value is None:
                    value = "unknown"
                elif isinstance(value, (int, float)):
                    value = str(value)
                elif not isinstance(value, str):
                    value = str(value)
                metadata_values.append(value.lower().strip())
            
            # Create metadata tuple as key
            metadata_key = tuple(metadata_values)
            
            if metadata_key not in metadata_groups:
                metadata_groups[metadata_key] = []
            metadata_groups[metadata_key].append(idx)
        
        logger.info(
            "  Level %d grouping by %s: %d groups",
            current_level,
            grouping_keys,
            len(metadata_groups),
        )
        
        all_clusters = []
        
        # Convert metadata groups to clusters
        for metadata_key, group_indices in metadata_groups.items():
            group_indices = np.array(group_indices)
            
            # If group is small enough, keep as single cluster
            if len(group_indices) <= self.max_cluster_size:
                all_clusters.append(group_indices)
            else:
                # If group is too large, perform embedding-based sub-clustering
                group_embeddings = embeddings[group_indices]
                reduced = self.global_cluster_embeddings(group_embeddings, dim=dim)
                
                if self.clustering_algorithm == "gaussian_mixture":
                    sub_clusters = self.gmm_clustering(reduced, threshold=threshold)
                elif self.clustering_algorithm == "kmeans":
                    n_clusters = max(2, len(group_indices) // self.max_cluster_size)
                    kmeans = KMeans(n_clusters=n_clusters, random_state=42)
                    labels = kmeans.fit_predict(reduced)
                    sub_clusters = [np.where(labels == i)[0] for i in range(n_clusters)]
                else:
                    sub_clusters = [np.arange(len(group_indices))]
                
                # Map back to original indices
                for sub_cluster in sub_clusters:
                    if len(sub_cluster) >= self.min_cluster_size:
                        all_clusters.append(group_indices[sub_cluster])
        
        return all_clusters
    
    def perform_clustering_with_nodes(
        self,
        nodes: List,
        embeddings: np.ndarray,
        current_level: int = None,
        dim: int = 10,
        threshold: float = 0.5
    ) -> List[np.ndarray]:
        """
        Perform clustering with optional metadata support.
        
        Args:
            nodes: List of nodes with metadata
            embeddings: Embeddings for the nodes
            current_level: Current level being built (for fixed hierarchical clustering)
            dim: Dimension for reduction
            threshold: Clustering threshold
        
        Returns:
            List of clusters (each cluster is an array of indices)
        """
        if self.use_metadata_clustering and nodes is not None:
            if current_level is not None:
                # Use fixed hierarchical clustering
                return self.perform_fixed_hierarchical_clustering(
                    nodes, embeddings, current_level, dim, threshold
                )
            else:
                # Use original metadata clustering
                return self.perform_metadata_clustering(nodes, embeddings, dim, threshold)
        else:
            return self.perform_clustering(embeddings, dim, threshold)
