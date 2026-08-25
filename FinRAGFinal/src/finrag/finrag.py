"""Main FinRAG implementation combining all components."""
from typing import List, Dict, Any, Optional, Tuple
import logging
import numpy as np
from pathlib import Path
import PyPDF2
import warnings
import tiktoken

from .config import FinRAGConfig
from .models import (
    OpenAIEmbeddingModel,
    OpenAISummarizationModel,
    OpenAIQAModel,
    FinancialChunker
)
from .models.fallback_models import (
    SentenceTransformerEmbeddingModel,
    FlanT5SummarizationModel,
    FlanT5QAModel,
    check_openai_key_valid
)
from .core.tree import RAPTORTree, TreeConfig
from .core.retrieval import RAPTORRetriever
from .core.retrieval_pathway import RAPTORRetriever as RAPTORRetrieverPathway
from .utils.filtered_parser import FilteredDocumentParser
from .vectorstore import PathwayVectorStore, PathwayConfig
try:
    from .vectorstore import ChromaVectorStore, ChromaConfig
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    ChromaVectorStore = None
    ChromaConfig = None
from .observability import trace_document_parsing, flush_langfuse


logger = logging.getLogger(__name__)


class FinRAG:
    """
    Main FinRAG class implementing retrieval-augmented generation
    with RAPTOR-style hierarchical indexing for financial documents.
    """
    
    def __init__(
        self, 
        config: FinRAGConfig = None, 
        use_pathway: bool = False, 
        pathway_config: PathwayConfig = None,
        use_chromadb: bool = True,
        chroma_config: ChromaConfig = None
    ):
        """
        Initialize FinRAG system.
        
        Args:
            config: FinRAG configuration
            use_pathway: Whether to use Pathway vector store for embeddings (default: False, legacy)
            pathway_config: Pathway configuration (optional, legacy)
            use_chromadb: Whether to use ChromaDB vector store (default: True)
            chroma_config: ChromaDB configuration (optional)
        """
        self.config = config or FinRAGConfig()
        self.use_pathway = use_pathway or self.config.use_pathway_vectorstore
        self.pathway_config = pathway_config
        
        # ChromaDB configuration (default to True if available)
        self.use_chromadb = use_chromadb and self.config.use_chromadb and CHROMADB_AVAILABLE
        if self.use_chromadb and chroma_config is None:
            # Create default ChromaDB config
            if CHROMADB_AVAILABLE:
                chroma_config = ChromaConfig(
                    collection_name=self.config.chroma_collection_name,
                    dimension=1536 if check_openai_key_valid(self.config.openai_api_key) else 384
                )
            else:
                self.use_chromadb = False
                warnings.warn(
                    "ChromaDB not available. Install with: pip install chromadb. "
                    "Falling back to Pathway or in-memory storage.",
                    RuntimeWarning
                )
        self.chroma_config = chroma_config
        
        # Check if OpenAI API key is available and valid
        has_openai = check_openai_key_valid(self.config.openai_api_key)
        
        if not has_openai:
            warnings.warn(
                "OpenAI API key was not provided. Falling back to open-source models. "
                "Set the OPENAI_API_KEY environment variable to enable OpenAI endpoints.",
                RuntimeWarning,
            )
        
        # Initialize models with fallback
        if has_openai:
            self.embedding_model = OpenAIEmbeddingModel(
                model=self.config.embedding_model,
                api_key=self.config.openai_api_key
            )
            
            self.summarization_model = OpenAISummarizationModel(
                model=self.config.summarization_model,
                api_key=self.config.openai_api_key
            )
            
            self.qa_model = OpenAIQAModel(
                model=self.config.llm_model,
                api_key=self.config.openai_api_key
            )
        else:
            # Use fallback models (free, open-source AI)
            self.embedding_model = SentenceTransformerEmbeddingModel(
                model="all-MiniLM-L6-v2"
            )
            
            self.summarization_model = FlanT5SummarizationModel(
                model_name="google/flan-t5-small"
            )
            
            self.qa_model = FlanT5QAModel(
                model_name="google/flan-t5-small"
            )
        
        self.chunker = FinancialChunker(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap
        )
        
        # Initialize tree
        tree_config = TreeConfig(
            max_depth=self.config.tree_depth,
            max_cluster_size=self.config.max_cluster_size,
            min_cluster_size=self.config.min_cluster_size,
            summarization_length=self.config.summarization_length
        )
        
        # Pass vectorstore config to tree (ChromaDB preferred, Pathway fallback)
        self.tree = RAPTORTree(
            embedding_model=self.embedding_model,
            summarization_model=self.summarization_model,
            config=tree_config,
            use_metadata_clustering=self.config.use_metadata_clustering,
            pathway_config=self.pathway_config if self.use_pathway and not self.use_chromadb else None,
            chroma_config=self.chroma_config,
            use_chromadb=self.use_chromadb
        )
        
        self.retriever = None
    
    def load_pdf(
        self, 
        pdf_path: str, 
        use_llamaparse: bool = None,
        use_filtering: bool = False,
        sections_to_extract: Optional[List[str]] = None
    ) -> str:
        """Load text from a PDF file using LlamaParse or PyPDF2."""
        if use_llamaparse is None:
            use_llamaparse = self.config.use_llamaparse
        
        if use_filtering is None:
            use_filtering = getattr(self.config, 'use_filtered_parsing', False)
        
        # Try LlamaParse first if enabled and API key is available
        if use_llamaparse and self.config.llamaparse_api_key:
            try:
                from llama_cloud_services import LlamaParse
                
                # Use filtered parsing if enabled
                if use_filtering:
                    self._log("Using LlamaParse with intelligent filtering...")
                    
                    # Initialize filtered parser
                    filtered_parser = FilteredDocumentParser(
                        sections_to_extract=sections_to_extract
                    )
                    
                    # Generate system prompt for section extraction
                    system_prompt = filtered_parser.generate_system_prompt()
                    
                    # Parse with custom prompt
                    parser = LlamaParse(
                        api_key=self.config.llamaparse_api_key,
                        num_workers=10,
                        verbose=False,
                        target_pages = "1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95,96,97,98,99,100",
                        parse_mode="parse_with_llm",  # Use LLM mode for filtering
                        language=self.config.llamaparse_language,
                    )
                    
                    result = parser.parse(pdf_path)
                    raw_markdown = result.get_markdown()
                    
                    # Consolidate and filter sections
                    consolidated_data = filtered_parser.consolidate_sections(raw_markdown)
                    
                    # Get statistics
                    stats = filtered_parser.get_statistics(consolidated_data)
                    self._log(
                        "Filtered parsing complete: "
                        f"sections={stats['total_sections']}, items={stats['total_items']}, "
                        f"coverage={stats['coverage']:.1f}%"
                    )
                    
                    # Convert to text format for embedding
                    text = filtered_parser.convert_to_text(consolidated_data)
                    
                    # Optionally save outputs for debugging
                    if hasattr(self.config, 'save_filtered_outputs') and self.config.save_filtered_outputs:
                        output_dir = Path(pdf_path).parent / "filtered_outputs"
                        base_name = Path(pdf_path).stem
                        saved_files = filtered_parser.save_outputs(
                            consolidated_data, 
                            str(output_dir),
                            base_name
                        )
                        self._log(f"Filtered outputs saved to {output_dir}")
                    
                    self._log(
                        "Filtered text prepared: "
                        f"length={len(text)} characters (original {len(raw_markdown)})"
                    )
                    return text
                
                else:
                    # Standard LlamaParse without filtering
                    self._log("Using LlamaParse for document extraction...")
                    parser = LlamaParse(
                        api_key=self.config.llamaparse_api_key,
                        num_workers=self.config.llamaparse_num_workers,
                        verbose=False,
                        target_pages = "1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95,96,97,98,99,100",
                        parse_mode=self.config.llamaparse_mode,
                        language=self.config.llamaparse_language
                    )
                    
                    result = parser.parse(pdf_path)
                    text = result.get_markdown()
                    self._log(f"Parsed with LlamaParse: {len(text)} characters")
                    return text
                
            except ImportError:
                logger.warning(
                    "LlamaParse is not installed. Install with 'pip install llama-parse llama-cloud-services'."
                )
            except Exception as e:
                logger.warning("LlamaParse failed with error: %s", str(e))
        
        # Fallback to PyPDF2
        self._log("Using PyPDF2 for text extraction...")
        text = ""
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
            self._log(f"Parsed with PyPDF2: {len(text)} characters")
        except Exception as e:
            logger.error("PyPDF2 failed with error: %s", str(e))
            raise
        
        return text
    
    def load_text(self, text_path: str) -> str:
        """
        Load text from a text file.
        
        Args:
            text_path: Path to text file
        
        Returns:
            File content
        """
        with open(text_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    def parse_document_traced(
        self,
        pdf_path: str,
        ticker: Optional[str] = None,
        company_name: Optional[str] = None,
        document_type: str = "annual_report",
        use_llamaparse: bool = None,
        use_filtering: bool = False,
        return_usage: bool = True
    ) -> Tuple[str, List[Dict[str, Any]], np.ndarray, Optional[Dict[str, Any]]]:
        """
        Parse a single document with full Langfuse tracing.
        """
        import time
        start_time = time.time()
        
        # Initialize token counter for embeddings
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
        except:
            encoding = None
        
        # Usage tracking
        usage_stats = {
            "file_path": pdf_path,
            "ticker": ticker,
            "extraction": {},
            "chunking": {},
            "embedding": {},
            "total": {}
        }
        
        with trace_document_parsing(
            file_path=pdf_path,
            ticker=ticker,
            company_name=company_name,
            document_type=document_type,
            tags=["parse_document", "single_doc"]
        ) as trace:
            
            # Step 1: PDF Extraction
            extraction_start = time.time()
            with trace.span(
                "pdf_extraction",
                input={"file_path": pdf_path, "use_llamaparse": use_llamaparse},
                metadata={"parser": "llamaparse" if use_llamaparse else "pypdf2"}
            ):
                text = self.load_pdf(
                    pdf_path,
                    use_llamaparse=use_llamaparse,
                    use_filtering=use_filtering
                )
                
                trace.event(
                    name="extraction_complete",
                    output={
                        "text_length": len(text),
                        "page_count_estimate": len(text) // 3000  # rough estimate
                    }
                )
            
            usage_stats["extraction"] = {
                "text_length": len(text),
                "page_count_estimate": len(text) // 3000,
                "time_seconds": round(time.time() - extraction_start, 2)
            }
            
            # Step 2: Chunking
            chunking_start = time.time()
            with trace.span(
                "chunking",
                input={"text_length": len(text)},
                metadata={
                    "chunk_size": self.config.chunk_size,
                    "chunk_overlap": self.config.chunk_overlap,
                    "use_metadata_clustering": self.config.use_metadata_clustering
                }
            ):
                if self.config.use_metadata_clustering:
                    chunks = self.chunker.chunk_text_with_metadata(text)
                else:
                    chunks = self.chunker.chunk_text(text)
                
                trace.event(
                    name="chunking_complete",
                    output={
                        "chunk_count": len(chunks),
                        "avg_chunk_length": sum(len(c.get("text", "")) for c in chunks) / len(chunks) if chunks else 0
                    }
                )
            
            avg_chunk_len = sum(len(c.get("text", "")) for c in chunks) / len(chunks) if chunks else 0
            usage_stats["chunking"] = {
                "chunk_count": len(chunks),
                "avg_chunk_length": round(avg_chunk_len, 0),
                "time_seconds": round(time.time() - chunking_start, 2)
            }
            
            # Step 3: Embedding Creation
            embedding_start = time.time()
            with trace.span(
                "embedding",
                input={"chunk_count": len(chunks)},
                metadata={"embedding_model": getattr(self.embedding_model, 'model', 'unknown')}
            ):
                batch_size = 100
                embeddings_list = []
                total_tokens = 0
                
                for i in range(0, len(chunks), batch_size):
                    batch = chunks[i:i+batch_size]
                    batch_texts = [chunk["text"] for chunk in batch]
                    
                    # Count tokens for this batch
                    if encoding:
                        batch_tokens = sum(len(encoding.encode(t)) for t in batch_texts)
                        total_tokens += batch_tokens
                    
                    batch_embeddings = self.embedding_model.create_embeddings(batch_texts)
                    embeddings_list.append(batch_embeddings)
                
                embeddings = np.vstack(embeddings_list)
                
                # Record embedding generation (this is an API call with costs)
                embedding_model_name = getattr(self.embedding_model, 'model', 'text-embedding-3-small')
                trace.generation(
                    name="embedding_batch",
                    model=embedding_model_name,
                    input={"chunk_count": len(chunks), "total_chars": sum(len(c.get("text", "")) for c in chunks)},
                    output=f"Generated {len(embeddings)} embeddings",
                    usage={
                        "prompt_tokens": total_tokens,
                        "completion_tokens": 0,
                        "total_tokens": total_tokens
                    },
                    metadata={
                        "embedding_dimension": embeddings.shape[1] if len(embeddings.shape) > 1 else 0,
                        "batch_count": len(embeddings_list)
                    }
                )
            
            # Calculate embedding cost
            # text-embedding-3-small: $0.00002 per 1K tokens
            embedding_cost = (total_tokens / 1000) * 0.00002
            
            usage_stats["embedding"] = {
                "total_tokens": total_tokens,
                "embedding_model": embedding_model_name,
                "embedding_dimension": embeddings.shape[1] if len(embeddings.shape) > 1 else 0,
                "cost_usd": round(embedding_cost, 6),
                "time_seconds": round(time.time() - embedding_start, 2)
            }
            
            # Total stats
            total_time = time.time() - start_time
            usage_stats["total"] = {
                "time_seconds": round(total_time, 2),
                "total_tokens": total_tokens,
                "total_cost_usd": round(embedding_cost, 6)  # Only embedding costs for parsing
            }
            
            # Update trace with final summary
            trace.update_metadata(
                text_length=len(text),
                chunk_count=len(chunks),
                embedding_count=len(embeddings),
                total_tokens=total_tokens
            )
            
            # Flush traces
            flush_langfuse()
            
            # Print summary
            print("\n" + "="*50)
            print("DOCUMENT PARSING USAGE SUMMARY")
            print("="*50)
            print(f"File: {Path(pdf_path).name}")
            print(f"Company: {company_name or 'Unknown'} ({ticker or 'N/A'})")
            print("-"*50)
            print(f"Extraction: {usage_stats['extraction']['text_length']:,} chars ({usage_stats['extraction']['time_seconds']}s)")
            print(f"Chunking: {usage_stats['chunking']['chunk_count']} chunks ({usage_stats['chunking']['time_seconds']}s)")
            print(f"Embedding: {total_tokens:,} tokens ({usage_stats['embedding']['time_seconds']}s)")
            print("-"*50)
            print(f"Cost: ${embedding_cost:.6f}")
            print(f"Total Time: {total_time:.2f}s")
            print("="*50 + "\n")
            
            if return_usage:
                return text, chunks, embeddings, usage_stats
            return text, chunks, embeddings, None
    
    def add_documents(self, documents: List[str]) -> None:
        """Add documents to the RAPTOR tree."""
        self._log("Chunking documents...")
        all_chunks = []
        for doc in documents:
            # Use metadata extraction if metadata clustering is enabled
            if self.config.use_metadata_clustering:
                chunks = self.chunker.chunk_text_with_metadata(doc)
            else:
                chunks = self.chunker.chunk_text(doc)
            all_chunks.extend(chunks)
        
        self._log(f"Created {len(all_chunks)} chunks")
        
        self._log("Creating embeddings...")
        # Create embeddings in batches
        batch_size = 100
        embeddings_list = []
        
        for i in range(0, len(all_chunks), batch_size):
            batch = all_chunks[i:i+batch_size]
            batch_texts = [chunk["text"] for chunk in batch]
            batch_embeddings = self.embedding_model.create_embeddings(batch_texts)
            embeddings_list.append(batch_embeddings)
        
        embeddings = np.vstack(embeddings_list)
        self._log(f"Created {len(embeddings)} embeddings")
        
        self._log("Building RAPTOR tree...")
        self.tree.build_tree(all_chunks, embeddings)
        
        self._log("Initializing retriever...")
        if self.use_pathway:
            self.retriever = RAPTORRetrieverPathway(
                tree=self.tree,
                embedding_model=self.embedding_model,
                top_k=70,  # Increased to 70 for better recall
                use_pathway=True,
                pathway_config=self.pathway_config,
                use_hybrid=True,  # Enable hybrid search
                hybrid_alpha=0.6  # 60% semantic, 40% BM25 for better keyword matching
            )
            self._log("Using Pathway vector store with hybrid search for retrieval")
        else:
            self.retriever = RAPTORRetriever(
                tree=self.tree,
                embedding_model=self.embedding_model,
                top_k=50  # Increased from config default to 50
            )
        
        self._log("FinRAG system is ready.")
    
    def add_documents_incremental(self, documents: List[str]) -> None:
        """Incrementally add new documents to an existing RAPTOR tree."""
        if not self.tree.all_nodes:
            raise RuntimeError(
                "No existing tree found. Use add_documents() to build the initial tree first."
            )
        
        self._log("Processing new documents for incremental addition...")
        
        # Chunk new documents
        self._log("Chunking new documents...")
        all_chunks = []
        for doc in documents:
            # Use metadata extraction if metadata clustering is enabled
            if self.config.use_metadata_clustering:
                chunks = self.chunker.chunk_text_with_metadata(doc)
            else:
                chunks = self.chunker.chunk_text(doc)
            all_chunks.extend(chunks)
        
        self._log(f"Created {len(all_chunks)} new chunks")
        
        # Create embeddings for new chunks
        self._log("Creating embeddings for new chunks...")
        batch_size = 100
        embeddings_list = []
        
        for i in range(0, len(all_chunks), batch_size):
            batch = all_chunks[i:i+batch_size]
            batch_texts = [chunk["text"] for chunk in batch]
            batch_embeddings = self.embedding_model.create_embeddings(batch_texts)
            embeddings_list.append(batch_embeddings)
        
        embeddings = np.vstack(embeddings_list)
        self._log(f"Created {len(embeddings)} embeddings")
        
        # Add to tree incrementally
        self._log("Updating RAPTOR tree incrementally...")
        self.tree.add_documents_incremental(all_chunks, embeddings)
        
        # Retriever automatically uses updated tree (no reinit needed)
        self._log("Tree updated successfully. Retriever is using updated tree.")
    
    def query(
        self,
        question: str,
        retrieval_method: str = None,
        top_k: int = None
    ) -> Dict[str, Any]:
        """Query the FinRAG system."""
        if self.retriever is None:
            raise RuntimeError("No documents added. Call add_documents() first.")
        
        if retrieval_method is None:
            retrieval_method = self.config.traversal_method
        
        if top_k is None:
            top_k = self.config.top_k
        
        # Retrieve relevant context
        self._log(f"Retrieving context using {retrieval_method}...")
        self._log(f"Retriever type: {type(self.retriever).__name__}")
        if hasattr(self.retriever, 'use_pathway'):
            self._log(f"Using Pathway: {self.retriever.use_pathway}")
        if hasattr(self.retriever, 'vector_store'):
            self._log(f"Vector store available: {self.retriever.vector_store is not None}")
        
        context = self.retriever.retrieve_with_context(
            question,
            method=retrieval_method,
            k=top_k,
            include_children=True  # Include children context for richer information
        )
        
        # Retrieve nodes for metadata
        retrieved_nodes = self.retriever.retrieve(question, retrieval_method, top_k)
        
        # Answer question
        self._log("Generating answer...")
        result = self.qa_model.answer_question(context, question)
        result["retrieved_nodes"] = [
            {
                "node_id": node.node_id,
                "level": node.level,
                "score": float(score),
                "text": node.text,  # Include full text for evaluation
                "text_preview": node.text[:200] + "..." if len(node.text) > 200 else node.text
            }
            for node, score in retrieved_nodes
        ]
        result["retrieval_method"] = retrieval_method
        
        return result
    
    def save(self, path: str) -> None:
        """Save the FinRAG system to disk."""
        save_path = Path(path)
        save_path.mkdir(parents=True, exist_ok=True)
        
        # Save tree
        self.tree.save(path)
        
        self._log(f"FinRAG state saved to {path}.")
    
    def load(self, path: str) -> None:
        """Load a saved FinRAG system from disk."""
        self.tree = RAPTORTree.load(
            path,
            self.embedding_model,
            self.summarization_model,
            pathway_config=self.pathway_config if self.use_pathway and not self.use_chromadb else None,
            chroma_config=self.chroma_config,
            use_chromadb=self.use_chromadb
        )
        
        # Initialize retriever (will auto-detect ChromaDB or Pathway from tree)
        if self.use_pathway or (hasattr(self.tree, 'vectorstore') and self.tree.vectorstore is not None):
            self.retriever = RAPTORRetrieverPathway(
                tree=self.tree,
                embedding_model=self.embedding_model,
                top_k=self.config.top_k,
                use_pathway=True,
                pathway_config=self.pathway_config
            )
            self._log("Loaded with Pathway vector store")
        else:
            self.retriever = RAPTORRetriever(
                tree=self.tree,
                embedding_model=self.embedding_model,
                top_k=self.config.top_k
            )
        
        self._log(f"FinRAG state loaded from {path}.")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about the current tree."""
        if not self.tree.all_nodes:
            return {"message": "No documents added yet"}
        
        levels = {}
        for node in self.tree.all_nodes.values():
            levels[node.level] = levels.get(node.level, 0) + 1
        
        return {
            "total_nodes": len(self.tree.all_nodes),
            "leaf_nodes": len(self.tree.leaf_nodes),
            "root_nodes": len(self.tree.root_nodes),
            "levels": levels,
            "tree_depth": max(levels.keys()) if levels else 0
        }

    def _log(self, message: str, level: int = logging.INFO) -> None:
        """Log helper that respects the verbose flag while surfacing warnings."""
        if level >= logging.WARNING or self.config.verbose:
            logger.log(level, message)
