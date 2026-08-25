"""Pathway VectorStore implementation for FinRAG with NumPy fallback."""

from __future__ import annotations
import logging
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass
from pathlib import Path
import json
import tempfile
import shutil
import asyncio
import numpy as np

logger = logging.getLogger(__name__)

# Try to import Pathway components; keep graceful fallback
try:
    import pathway as pw
    from pathway.xpacks.llm.vector_store import VectorStoreServer, VectorStoreClient
    PATHWAY_AVAILABLE = True
    PATHWAY_ERROR = None
except Exception as e:
    PATHWAY_AVAILABLE = False
    PATHWAY_ERROR = str(e)
    pw = None
    VectorStoreServer = None
    VectorStoreClient = None

# Preserve original ClusterNode import logic exactly (important for your project layout)
try:
    from ..core.clustering import ClusterNode
except ImportError:
    # Fallback for direct script execution
    import sys
    from pathlib import Path as _Path
    root_path = _Path(__file__).parent.parent.parent
    if str(root_path) not in sys.path:
        sys.path.insert(0, str(root_path))
    from finrag.core.clustering import ClusterNode


@dataclass
class PathwayConfig:
    host: str = "127.0.0.1"
    port: int = 8754
    dimension: int = 1536
    metric: str = "cosine"
    index_type: str = "usearch"
    enable_streaming: bool = False
    persistence_path: Optional[str] = None

    def __post_init__(self) -> None:
        if not PATHWAY_AVAILABLE:
            import platform
            if platform.system() == "Windows":
                logger.warning(
                    "Pathway not installed or not available on this platform. "
                    "If you're on Windows, use WSL and install pathway[xpack-llm]. "
                    f"Underlying import error: {PATHWAY_ERROR}"
                )
            else:
                logger.warning(
                    "Pathway not installed. Falling back to NumPy backend. "
                    f"Underlying import error: {PATHWAY_ERROR}"
                )


class PathwayVectorStore:
    """Vector store using Pathway for ANN indexing or NumPy fallback."""

    def __init__(self, config: Optional[PathwayConfig] = None) -> None:
        self.config = config or PathwayConfig()

        # core data
        self.nodes: Dict[str, ClusterNode] = {}
        self.node_ids: List[str] = []
        self.embeddings: Optional[np.ndarray] = None
        self.embedding_cache: Dict[str, np.ndarray] = {}

        # state
        self.is_built: bool = False

        # Pathway objects (only used when enable_streaming=True and PATHWAY_AVAILABLE)
        self.server: Optional[Any] = None
        self.server_thread = None
        self.client: Optional[Any] = None
        self._temp_docs_dir: Optional[str] = None
        self.server_ready: bool = False

        # decide which backend to use
        self.use_pathway = PATHWAY_AVAILABLE and self.config.enable_streaming

        logger.info(f"PathwayVectorStore init: pathway_available={PATHWAY_AVAILABLE}, streaming={self.config.enable_streaming}")

    # ---------------- Node management ----------------
    def add_nodes(self, nodes: List[ClusterNode]) -> None:
        """Add ClusterNode objects with precomputed embeddings."""
        if not nodes:
            logger.debug("add_nodes called with empty list")
            return

        new_node_ids: List[str] = []
        for node in nodes:
            if node.node_id in self.nodes:
                # update node and embedding cache
                self.nodes[node.node_id] = node
                self.embedding_cache[node.node_id] = np.array(node.embedding, dtype=float)
            else:
                self.nodes[node.node_id] = node
                self.node_ids.append(node.node_id)
                self.embedding_cache[node.node_id] = np.array(node.embedding, dtype=float)
                new_node_ids.append(node.node_id)

        # rebuild local embeddings matrix
        self.embeddings = np.array([self.embedding_cache[nid] for nid in self.node_ids])
        self.is_built = False

        # If server client exists, push only the new documents
        if self.client and new_node_ids:
            docs = []
            for nid in new_node_ids:
                n = self.nodes[nid]
                docs.append({"text": n.text, "metadata": {"node_id": nid, "level": n.level, **(n.metadata or {})}})
            try:
                # client has async add methods; call them via asyncio.run when possible
                asyncio.run(self._client_add_documents(docs))
                logger.info(f"Pushed {len(docs)} docs to Pathway server")
            except RuntimeError:
                # If event loop is running in the caller (e.g., inside an async app), raise informative error
                raise RuntimeError("Cannot push documents from a running event loop — call async_add_documents() instead")
            except Exception as e:
                logger.warning(f"Failed to push documents to Pathway server: {e}")

        logger.info(f"add_nodes: added {len(new_node_ids)} new nodes (total={len(self.nodes)})")

    async def _client_add_documents(self, documents: List[Dict[str, Any]]) -> None:
        """Internal async helper to add documents via the Pathway client."""
        if not self.client:
            raise RuntimeError("Pathway client not initialized")

        # Prefer abstract method names that are commonly implemented
        if hasattr(self.client, "aadd_documents"):
            await self.client.aadd_documents(documents)
            return
        if hasattr(self.client, "aadd_texts"):
            texts = [d["text"] for d in documents]
            metadatas = [d.get("metadata", {}) for d in documents]
            await self.client.aadd_texts(texts, metadatas)
            return

        raise RuntimeError("Pathway client does not expose supported async add methods")

    # ---------------- Index build & server lifecycle ----------------
    def build_index(self) -> None:
        """Build the vector index."""
        if self.config.enable_streaming:
            if not PATHWAY_AVAILABLE:
                raise RuntimeError("Pathway not available: cannot start streaming server")
            if not self.server_ready:
                self.start_server()
            # server will build index internally
            self.is_built = True
            return

        # static
        if self.embeddings is None or len(self.embeddings) == 0:
            raise ValueError("No embeddings available. Call add_nodes() first.")
        self.is_built = True
        logger.info(f"Local NumPy index ready: {len(self.node_ids)} vectors")

    def start_server(self) -> None:
        """Start Pathway VectorStoreServer pipeline and HTTP server.

        Implementation notes:
          - Builds a temporary directory with one file per node (so fs.read() can
            attach _path metadata). The embedder UDF will *only* return
            precomputed embeddings from embedding_cache.
          - Uses VectorStoreServer(...) and its run_server(...) helper which
            starts an HTTP server in background. We then create a VectorStoreClient
            to communicate with it.
        """
        if not PATHWAY_AVAILABLE:
            raise RuntimeError("Pathway not installed or unavailable in this runtime")
        if self.server_ready:
            logger.info("Pathway server already running")
            return

        # write temp documents
        tmpdir = tempfile.mkdtemp(prefix="finrag_pathway_")
        self._temp_docs_dir = tmpdir
        for nid in self.node_ids:
            node = self.nodes[nid]
            (Path(tmpdir) / f"{nid}.txt").write_text(node.text, encoding="utf-8")

        # read into Pathway table
        docs_table = pw.io.fs.read(tmpdir, format="binary", mode="static", with_metadata=True)

        # embedder: accept bytes and metadata; return precomputed vector
        embedding_cache_ref = self.embedding_cache
        nodes_ref = self.nodes
        dim = self.config.dimension

        @pw.udf
        async def precomputed_embedder(data: bytes, metadata: dict) -> List[float]:
            # Pathway places file path in metadata['_path']
            node_id = None
            if metadata and "_path" in metadata:
                node_id = Path(metadata["_path"]).stem
            if node_id and node_id in embedding_cache_ref:
                return embedding_cache_ref[node_id].tolist()
            # fallback: try to match by text
            text = data.decode("utf-8", errors="ignore")
            for nid, n in nodes_ref.items():
                if n.text == text:
                    return embedding_cache_ref.get(nid, np.zeros(dim)).tolist()
            # last resort
            logger.warning("precomputed_embedder: missing embedding, returning zeros")
            return [0.0] * dim

        # minimal parser
        def minimal_parser(data: bytes) -> List[Tuple[str, Dict[str, Any]]]:
            text = data.decode("utf-8", errors="ignore")
            return [(text, {})]

        # create server pipeline
        self.server = VectorStoreServer(docs_table, embedder=precomputed_embedder, parser=minimal_parser, splitter=None)

        # start server (run_server returns a thread-like handle in many versions)
        try:
            thread = self.server.run_server(host=self.config.host, port=self.config.port, threaded=True, with_cache=True)
            self.server_thread = thread
            # create client
            self.client = VectorStoreClient(host=self.config.host, port=self.config.port)
            self.server_ready = True
            logger.info(f"Pathway VectorStore server running at http://{self.config.host}:{self.config.port}")
            # auto-push existing docs if client supports
            try:
                asyncio.run(self._client_get_statistics())
            except Exception:
                logger.debug("Unable to fetch server statistics immediately")
        except Exception as e:
            # cleanup
            logger.error(f"Failed to run Pathway VectorStore server: {e}")
            self._cleanup_temp_dir()
            self.server = None
            self.client = None
            self.server_ready = False
            raise

    def _cleanup_temp_dir(self) -> None:
        if self._temp_docs_dir:
            try:
                shutil.rmtree(self._temp_docs_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"cleanup temp dir failed: {e}")
            self._temp_docs_dir = None

    def stop_server(self) -> None:
        """Stop Pathway server and cleanup resources."""
        if not self.server_ready:
            logger.debug("stop_server called but server not running")
            return
        # best-effort cleanup: VectorStoreServer may not expose stop API
        try:
            # dereference client/server and cleanup temp files
            self.client = None
            self.server = None
            self.server_ready = False
            self._cleanup_temp_dir()
            logger.info("Pathway server stopped (best-effort)")
        except Exception as e:
            logger.warning(f"Error stopping server: {e}")

    async def _client_get_statistics(self) -> Dict[str, Any]:
        if not self.client:
            raise RuntimeError("Pathway client not initialized")
        if hasattr(self.client, "get_vectorstore_statistics"):
            return await self.client.get_vectorstore_statistics()
        return {}

    # ---------------- Search ----------------
    def search(self, query_embedding: Optional[np.ndarray] = None, k: int = 10, filter_level: Optional[int] = None, filter_metadata: Optional[Dict[str, Any]] = None) -> List[Tuple[ClusterNode, float]]:
        """Search the store. If server is available use remote client, otherwise local NumPy fallback.

        Notes:
        - If you call this from an async runtime, use async_query on server-backed class.
        """
        if not self.is_built:
            self.build_index()

        if self.server_ready and self.client is not None:
            # prefer vector search; if caller is in running event loop they must call async_query
            if query_embedding is None:
                raise ValueError("query_embedding required for search when using vector search")
            emb_list = np.asarray(query_embedding).tolist()
            # metadata filter passed as dict to client
            md_filter = filter_metadata or ({"level": filter_level} if filter_level is not None else None)
            try:
                # client methods are async; call synchronously only when no running loop
                try:
                    loop = asyncio.get_running_loop()
                    # running loop -> we cannot sync-block; advise user
                    raise RuntimeError("Cannot call synchronous search from a running async loop. Use async_query instead.")
                except RuntimeError:
                    # no running loop, safe to run
                    results = asyncio.run(self.client.similarity_search_by_vector(emb_list, k=k, metadata_filter=md_filter))
            except Exception as e:
                logger.warning(f"Pathway client search failed: {e}. Falling back to NumPy.")
                return self._numpy_search(query_embedding, k, filter_level, filter_metadata)

            normalized: List[Tuple[ClusterNode, float]] = []
            for item in results:
                # item can be dict-like
                meta = item.get("metadata") if isinstance(item, dict) else getattr(item, "metadata", {})
                score = item.get("score") if isinstance(item, dict) else getattr(item, "score", 0.0)
                nid = meta.get("node_id") if isinstance(meta, dict) else None
                if nid and nid in self.nodes:
                    normalized.append((self.nodes[nid], float(score)))
            return normalized

        # fallback: local NumPy
        return self._numpy_search(query_embedding, k, filter_level, filter_metadata)

    def _numpy_search(self, query_embedding: Optional[np.ndarray], k: int = 10, filter_level: Optional[int] = None, filter_metadata: Optional[Dict[str, Any]] = None) -> List[Tuple[ClusterNode, float]]:
        if query_embedding is None:
            raise ValueError("Local search requires query_embedding")
        if self.embeddings is None or len(self.embeddings) == 0:
            raise ValueError("No embeddings available for local search")

        # apply filters
        valid_indices = []
        for idx, nid in enumerate(self.node_ids):
            node = self.nodes[nid]
            if filter_level is not None and node.level != filter_level:
                continue
            if filter_metadata:
                ok = all(node.metadata.get(k) == v for k, v in filter_metadata.items())
                if not ok:
                    continue
            valid_indices.append(idx)

        if not valid_indices:
            return []

        valid_emb = self.embeddings[valid_indices]
        if self.config.metric == "cosine":
            from sklearn.metrics.pairwise import cosine_similarity
            sims = cosine_similarity([query_embedding], valid_emb)[0]
        elif self.config.metric == "l2":
            dists = np.linalg.norm(valid_emb - query_embedding, axis=1)
            sims = 1.0 / (1.0 + dists)
        elif self.config.metric == "ip":
            sims = np.dot(valid_emb, query_embedding)
        else:
            raise ValueError(f"Unknown metric: {self.config.metric}")

        top_k = min(k, len(sims))
        idxs = np.argsort(sims)[-top_k:][::-1]
        results: List[Tuple[ClusterNode, float]] = []
        for i in idxs:
            orig_idx = valid_indices[i]
            nid = self.node_ids[orig_idx]
            results.append((self.nodes[nid], float(sims[i])))
        return results

    # ---------------- Utilities ----------------
    def search_by_metadata(self, metadata_filters: Dict[str, Any], k: Optional[int] = None) -> List[ClusterNode]:
        results: List[ClusterNode] = []
        for nid in self.node_ids:
            node = self.nodes[nid]
            if all(node.metadata.get(k) == v for k, v in metadata_filters.items()):
                results.append(node)
                if k and len(results) >= k:
                    break
        return results

    def get_node(self, node_id: str) -> Optional[ClusterNode]:
        return self.nodes.get(node_id)

    def get_all_nodes(self) -> List[ClusterNode]:
        return [self.nodes[nid] for nid in self.node_ids]

    def get_statistics(self) -> Dict[str, Any]:
        if not self.nodes:
            return {"total_nodes": 0}
        levels: Dict[int, int] = {}
        for nid in self.node_ids:
            lvl = self.nodes[nid].level
            levels[lvl] = levels.get(lvl, 0) + 1
        return {
            "total_nodes": len(self.nodes),
            "embedding_dimension": self.config.dimension,
            "metric": self.config.metric,
            "is_built": self.is_built,
            "using_pathway": self.use_pathway,
            "server_ready": self.server_ready,
            "levels": levels,
        }

    # ---------------- Persistence ----------------
    def save(self, path: str) -> None:
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        with open(p / "pathway_config.json", "w", encoding="utf-8") as f:
            json.dump(self.config.__dict__, f, indent=2)
        node_data = {"node_ids": self.node_ids, "nodes": {}}
        for nid in self.node_ids:
            n = self.nodes[nid]
            node_data["nodes"][nid] = {
                "node_id": n.node_id,
                "text": n.text,
                "embedding": self.embedding_cache[nid].tolist(),
                "level": n.level,
                "metadata": n.metadata,
                "children_ids": [c.node_id for c in n.children],
            }
        with open(p / "pathway_nodes.json", "w", encoding="utf-8") as f:
            json.dump(node_data, f, indent=2)
        logger.info(f"Saved PathwayVectorStore to {p}")

    @classmethod
    def load(cls, path: str) -> "PathwayVectorStore":
        p = Path(path)
        with open(p / "pathway_config.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
        config = PathwayConfig(**cfg)
        store = cls(config)
        with open(p / "pathway_nodes.json", "r", encoding="utf-8") as f:
            node_data = json.load(f)
        all_nodes: Dict[str, ClusterNode] = {}
        for nid, data in node_data["nodes"].items():
            all_nodes[nid] = ClusterNode(
                node_id=data["node_id"],
                text=data["text"],
                embedding=np.array(data["embedding"]),
                children=[],
                level=data.get("level", 0),
                metadata=data.get("metadata", {}),
            )
        for nid, data in node_data["nodes"].items():
            all_nodes[nid].children = [all_nodes[cid] for cid in data.get("children_ids", []) if cid in all_nodes]
        nodes_list = [all_nodes[nid] for nid in node_data["node_ids"]]
        store.add_nodes(nodes_list)
        logger.info(f"Loaded PathwayVectorStore from {p}")
        return store

    def clear(self) -> None:
        # stop server if running
        if self.server_ready:
            self.stop_server()
        self.nodes.clear()
        self.node_ids.clear()
        self.embedding_cache.clear()
        self.embeddings = None
        self.is_built = False
        logger.info("Cleared vector store")


class PathwayVectorStoreServer(PathwayVectorStore):
    """Convenience subclass that starts server-aware helpers."""

    def __init__(self, config: Optional[PathwayConfig] = None) -> None:
        config = config or PathwayConfig()
        config.enable_streaming = True
        super().__init__(config)

    async def async_query(self, query_embedding: List[float], k: int = 10, filter_metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Async query helper that calls client's async API directly.

        Use this when running inside an async event loop.
        """
        if not self.client:
            raise RuntimeError("Client not initialized; start_server() first")
        return await self.client.similarity_search_by_vector(query_embedding, k=k, metadata_filter=filter_metadata)


# End of module
