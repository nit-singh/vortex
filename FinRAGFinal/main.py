"""
FinRAG - Complete Financial RAG System with Pathway VectorStore

This is the main entry point demonstrating all core features:
1. Building a RAPTOR tree with Pathway VectorStore
2. Incrementally updating the tree with new documents
3. Querying the tree for information retrieval
4. Scoring stocks using the financial scoring pipeline

Usage:
    python main.py --mode [build|update|query|score|all]
    
Examples:
    # Build initial tree
    python main.py --mode build
    
    # Update existing tree
    python main.py --mode update
    
    # Query the tree
    python main.py --mode query --question "What is Apple's performance?"
    
    # Score a stock
    python main.py --mode score --ticker AAPL
    
    # Run full pipeline
    python main.py --mode all --ticker MSFT

Configuration:
    - Pathway VectorStore is used as PRIMARY storage for embeddings
    - JSON is used as backup/structure only
    - Metadata clustering enabled for hierarchical organization
    - Supports both OpenAI and open-source models
"""

import sys
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging
import json
import hashlib

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from finrag.utils import load_env_file
load_env_file()

from finrag import FinRAG, FinRAGConfig
from finrag.vectorstore import PathwayConfig
try:
    from finrag.vectorstore import ChromaConfig
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    ChromaConfig = None
from finrag.scoring import EnsembleScorer, ScoringConfig
from finrag.portfolio import PortfolioManager, PortfolioAnalyzer
from finrag.retrieval import (
    TickerExtractor,
    IntentAnalyzer,
    MultiSourceRetriever,
    FundamentalDataCache
)
from finrag.orchestrator import FinRAGOrchestrator, OrchestratorConfig
from finrag.observability import flush_langfuse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FinRAGPipeline:
    """
    Complete FinRAG pipeline with Pathway VectorStore integration.
    
    This class manages the entire workflow:
    - Tree building with Pathway as primary storage
    - Incremental updates
    - Query processing
    - Stock scoring
    """
    
    def __init__(
        self,
        tree_path: str = "finrag_tree",
        data_dir: str = "new_data",
        use_openai: bool = True
        
    ):
        """
        Initialize the FinRAG pipeline.
        
        Args:
            tree_path: Path to save/load the tree
            data_dir: Directory containing PDF documents
            use_openai: Whether to use OpenAI models (if False, uses open-source)
        """
        self.tree_path = Path(tree_path)
        self.data_dir = Path("new_data")
        self.cache_dir = Path("cache") / "parsed_docs"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Configure FinRAG
        self.config = FinRAGConfig()
        self.config.use_metadata_clustering = True  # Enable hierarchical clustering
        self.config.verbose = True
        
        # Configure ChromaDB VectorStore as PRIMARY storage (default)
        chroma_config = None
        if CHROMADB_AVAILABLE:
            chroma_config = ChromaConfig(
                collection_name="finrag_embeddings",
                dimension=1536 if use_openai else 384,  # OpenAI vs sentence-transformers
                persist_directory=None  # Will be set during save
            )
            logger.info("Initializing FinRAG with ChromaDB VectorStore as primary storage")
        else:
            # Fallback to Pathway if ChromaDB not available
            self.pathway_config = PathwayConfig(
                host="127.0.0.1",
                port=8754,
                dimension=1536 if use_openai else 384,
                metric="cosine",
                index_type="usearch",
                enable_streaming=False
            )
            logger.info("ChromaDB not available. Initializing FinRAG with Pathway VectorStore")
        
        # Initialize FinRAG with ChromaDB (default) or Pathway (fallback)
        self.finrag = FinRAG(
            config=self.config,
            use_pathway=not CHROMADB_AVAILABLE,  # Use Pathway only if ChromaDB unavailable
            pathway_config=self.pathway_config if not CHROMADB_AVAILABLE else None,
            use_chromadb=CHROMADB_AVAILABLE,
            chroma_config=chroma_config
        )
        
        # Initialize scoring components (lazy loading - will init when needed)
        self.ensemble_scorer = None
        self.scoring_config = ScoringConfig()
        
        # Initialize portfolio and enhanced retrieval components (lazy loading)
        self._portfolio_manager = None
        self._portfolio_analyzer = None
        self._ticker_extractor = None
        self._intent_analyzer = None
        self._fundamental_cache = None
        self._multi_source_retriever = None
        self._multi_source_retriever = None
    
    @property
    def portfolio_manager(self) -> PortfolioManager:
        """Lazy load portfolio manager."""
        if self._portfolio_manager is None:
            self._portfolio_manager = PortfolioManager("data/portfolio/portfolio.json")
        return self._portfolio_manager
    
    @property
    def portfolio_analyzer(self) -> PortfolioAnalyzer:
        """Lazy load portfolio analyzer."""
        if self._portfolio_analyzer is None:
            self._portfolio_analyzer = PortfolioAnalyzer(self.portfolio_manager)
        return self._portfolio_analyzer
    
    @property
    def ticker_extractor(self) -> TickerExtractor:
        """Lazy load ticker extractor."""
        if self._ticker_extractor is None:
            self._ticker_extractor = TickerExtractor(
                mapping_path="data/mappings/ticker_mapping.json",
                llm_model=self.finrag.qa_model if hasattr(self.finrag, 'qa_model') else None
            )
        return self._ticker_extractor
    
    @property
    def intent_analyzer(self) -> IntentAnalyzer:
        """Lazy load intent analyzer."""
        if self._intent_analyzer is None:
            self._intent_analyzer = IntentAnalyzer()
        return self._intent_analyzer
    
    @property
    def fundamental_cache(self) -> FundamentalDataCache:
        """Lazy load fundamental data cache."""
        if self._fundamental_cache is None:
            self._fundamental_cache = FundamentalDataCache(
                cache_dir="data/fundamentals",
                ttl_hours=24
            )
        return self._fundamental_cache
    
    @property
    def multi_source_retriever(self) -> MultiSourceRetriever:
        """Lazy load multi-source retriever."""
        if self._multi_source_retriever is None:
            self._multi_source_retriever = MultiSourceRetriever(
                ticker_extractor=self.ticker_extractor,
                intent_analyzer=self.intent_analyzer,
                fundamental_cache=self.fundamental_cache,
                portfolio_manager=self.portfolio_manager,
                portfolio_analyzer=self.portfolio_analyzer
            )
        return self._multi_source_retriever
    
    def build_tree(self, force_rebuild: bool = False) -> None:
        """
        Build the RAPTOR tree from all PDFs in data directory.
        
        Embeddings are stored in Pathway VectorStore (primary) and JSON (backup).
        
        Args:
            force_rebuild: If True, rebuilds even if tree exists
        """
        print("\n" + "=" * 80)
        print("BUILDING FINRAG TREE")
        print("=" * 80)
        
        # Check if tree already exists
        if self.tree_path.exists() and not force_rebuild:
            logger.info(f"Tree already exists at {self.tree_path}")
            logger.info("Use force_rebuild=True to rebuild")
            return
        
        # Get all PDFs
        pdf_files = list(self.data_dir.glob("*.pdf"))
        print(self.data_dir)
        if not pdf_files:
            logger.error(f"No PDF files found in {self.data_dir}")
            logger.error("Please add PDF files to the data folder")
            return
        
        logger.info(f"Found {len(pdf_files)} PDF files")
        for pdf in pdf_files:
            logger.info(f"  - {pdf.name}")
        
        # Process all PDFs with caching
        all_documents = []
        logger.info("\nProcessing PDFs...")
        
        for i, pdf_path in enumerate(pdf_files, 1):
            logger.info(f"[{i}/{len(pdf_files)}] Processing: {pdf_path.name}")
            try:
                # Try to load from cache first
                text = self._load_or_parse_pdf(str(pdf_path))
                all_documents.append(text)
                logger.info(f"  ✓ Loaded {len(text):,} characters")
            except Exception as e:
                logger.error(f"  ✗ Error: {e}")
                continue
        
        if not all_documents:
            logger.error("No documents were successfully processed!")
            return
        
        logger.info(f"\n✓ Successfully processed {len(all_documents)}/{len(pdf_files)} PDFs")
        
        # Build tree with Pathway VectorStore
        logger.info("\nBuilding RAPTOR tree with Pathway VectorStore...")
        logger.info("Primary storage: Pathway VectorStore (HNSW index)")
        logger.info("Backup storage: JSON (structure + embeddings)")
        
        self.finrag.add_documents(all_documents)
        
        # Get statistics
        stats = self.finrag.get_statistics()
        logger.info("\nTree Statistics:")
        for key, value in stats.items():
            logger.info(f"  {key}: {value}")
        
        # Save tree (both Pathway and JSON)
        logger.info(f"\nSaving tree to: {self.tree_path}")
        self.finrag.save(str(self.tree_path))
        
        # Verify Pathway VectorStore is active
        has_vectorstore = self.finrag.tree.vectorstore is not None
        logger.info(f"\n✓ Tree built successfully!")
        logger.info(f"  - Total nodes: {stats.get('total_nodes', 0)}")
        logger.info(f"  - Pathway VectorStore: {'✓ Active' if has_vectorstore else '✗ Not configured'}")
        logger.info(f"  - JSON backup: ✓ Saved")
        
        print("\n" + "=" * 80)
        print("BUILD COMPLETE")
        print("=" * 80)
    
    def update_tree(self, new_data_dir: str = None) -> None:
        """
        Incrementally update the tree with new documents from a folder.
        
        This is much faster than rebuilding from scratch.
        
        Args:
            new_data_dir: Path to folder containing new PDF files (if None, uses default new_data folder)
        """
        print("\n" + "=" * 80)
        print("UPDATING FINRAG TREE INCREMENTALLY")
        print("=" * 80)
        
        # Load existing tree
        if not self.tree_path.exists():
            logger.error(f"No existing tree found at {self.tree_path}")
            logger.error("Run build_tree() first")
            return
        
        logger.info(f"Loading existing tree from {self.tree_path}")
        self.finrag.load(str(self.tree_path))
        
        # Get initial statistics
        initial_stats = self.finrag.get_statistics()
        logger.info("\nInitial Tree Statistics:")
        for key, value in initial_stats.items():
            logger.info(f"  {key}: {value}")
        
        # Get new PDFs from specified directory
        if new_data_dir is None:
            new_data_dir = "update_data"
        
        new_data_path = Path(new_data_dir)
        if not new_data_path.exists():
            logger.error(f"Directory not found: {new_data_dir}")
            logger.error("Please create the directory and add PDF files")
            return
        
        logger.info(f"\nScanning for PDFs in: {new_data_path}")
        pdf_files = list(new_data_path.glob("*.pdf"))
        
        if not pdf_files:
            logger.info(f"No PDF files found in {new_data_dir}")
            return
        
        logger.info(f"Found {len(pdf_files)} new PDF(s):")
        for pdf in pdf_files:
            logger.info(f"  - {pdf.name}")
        
        new_pdf_paths = [str(pdf) for pdf in pdf_files]
        
        logger.info(f"\nProcessing {len(new_pdf_paths)} new PDF(s)...")
        
        # Process new PDFs with caching
        new_documents = []
        for i, pdf_path in enumerate(new_pdf_paths, 1):
            logger.info(f"[{i}/{len(new_pdf_paths)}] Processing: {Path(pdf_path).name}")
            try:
                # Try to load from cache first
                text = self._load_or_parse_pdf(pdf_path)
                new_documents.append(text)
                logger.info(f"  ✓ Loaded {len(text):,} characters")
            except Exception as e:
                logger.error(f"  ✗ Error: {e}")
                continue
        
        if not new_documents:
            logger.error("No new documents were successfully processed!")
            return
        
        # Update tree incrementally
        logger.info(f"\n✓ Successfully processed {len(new_documents)} new document(s)")
        logger.info("\nUpdating tree incrementally...")
        logger.info("  - Adding new leaf nodes")
        logger.info("  - Rebuilding parent layers")
        logger.info("  - Updating Pathway VectorStore")
        
        self.finrag.add_documents_incremental(new_documents)
        
        # Get updated statistics
        updated_stats = self.finrag.get_statistics()
        logger.info("\nUpdated Tree Statistics:")
        for key, value in updated_stats.items():
            logger.info(f"  {key}: {value}")
        
        # Show changes
        logger.info("\nChanges:")
        logger.info(f"  Total nodes: {initial_stats['total_nodes']} → {updated_stats['total_nodes']} "
                   f"(+{updated_stats['total_nodes'] - initial_stats['total_nodes']})")
        logger.info(f"  Leaf nodes: {initial_stats['leaf_nodes']} → {updated_stats['leaf_nodes']} "
                   f"(+{updated_stats['leaf_nodes'] - initial_stats['leaf_nodes']})")
        
        # Save updated tree
        logger.info(f"\nSaving updated tree to: {self.tree_path}")
        self.finrag.save(str(self.tree_path))
        
        logger.info("\n✓ Tree updated successfully!")
        logger.info("  - Pathway VectorStore: ✓ Updated")
        logger.info("  - JSON backup: ✓ Updated")
        
        print("\n" + "=" * 80)
        print("UPDATE COMPLETE")
        print("=" * 80)
    
    def update_tree_file(self, file_path: str) -> None:
        """
        Incrementally update the tree with a single new document file.
        
        This is much faster than rebuilding from scratch and useful when
        adding individual files rather than entire directories.
        
        Args:
            file_path: Path to the single PDF file to add to the tree
        """
        print("\n" + "=" * 80)
        print("UPDATING FINRAG TREE WITH SINGLE FILE")
        print("=" * 80)
        
        # Validate file path
        file_path = Path(file_path)
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return
        
        if not file_path.suffix.lower() == '.pdf':
            logger.error(f"File must be a PDF: {file_path}")
            return
        
        # Load existing tree
        if not self.tree_path.exists():
            logger.error(f"No existing tree found at {self.tree_path}")
            logger.error("Run build_tree() first")
            return
        
        logger.info(f"Loading existing tree from {self.tree_path}")
        self.finrag.load(str(self.tree_path))
        
        # Get initial statistics
        initial_stats = self.finrag.get_statistics()
        logger.info("\nInitial Tree Statistics:")
        for key, value in initial_stats.items():
            logger.info(f"  {key}: {value}")
        
        logger.info(f"\nProcessing file: {file_path.name}")
        
        # Process the single PDF with caching
        try:
            text = self._load_or_parse_pdf(str(file_path))
            logger.info(f"  ✓ Loaded {len(text):,} characters")
        except Exception as e:
            logger.error(f"  ✗ Error processing file: {e}")
            return
        
        # Update tree incrementally with single document
        logger.info("\nUpdating tree incrementally...")
        logger.info("  - Adding new leaf node")
        logger.info("  - Rebuilding parent layers")
        logger.info("  - Updating Pathway VectorStore")
        
        self.finrag.add_documents_incremental([text])
        
        # Get updated statistics
        updated_stats = self.finrag.get_statistics()
        logger.info("\nUpdated Tree Statistics:")
        for key, value in updated_stats.items():
            logger.info(f"  {key}: {value}")
        
        # Show changes
        logger.info("\nChanges:")
        logger.info(f"  Total nodes: {initial_stats['total_nodes']} → {updated_stats['total_nodes']} "
                   f"(+{updated_stats['total_nodes'] - initial_stats['total_nodes']})")
        logger.info(f"  Leaf nodes: {initial_stats['leaf_nodes']} → {updated_stats['leaf_nodes']} "
                   f"(+{updated_stats['leaf_nodes'] - initial_stats['leaf_nodes']})")
        
        # Save updated tree
        logger.info(f"\nSaving updated tree to: {self.tree_path}")
        self.finrag.save(str(self.tree_path))
        
        logger.info("\n✓ Tree updated successfully with single file!")
        logger.info(f"  - File added: {file_path.name}")
        logger.info("  - Pathway VectorStore: ✓ Updated")
        logger.info("  - JSON backup: ✓ Updated")
        
        print("\n" + "=" * 80)
        print("SINGLE FILE UPDATE COMPLETE")
        print("=" * 80)
    
    def query(self, question: str, method: str = "collapsed_tree", top_k: int = 10, quiet: bool = False) -> Dict[str, Any]:
        """
        Query the tree using Pathway VectorStore for similarity search.
        
        Args:
            question: Question to ask
            method: Retrieval method (tree_traversal, collapsed_tree, etc.)
            top_k: Number of results to retrieve
            quiet: If True, suppress console output (for orchestrator calls)
            
        Returns:
            Dictionary with answer and metadata
        """
        if not quiet:
            print("\n" + "=" * 80)
            print(f"QUERYING FINRAG TREE using {method} method")
            print("=" * 80)
        
        # Load tree if not already loaded
        if not self.finrag.tree.all_nodes:
            if not self.tree_path.exists():
                logger.error(f"No tree found at {self.tree_path}")
                logger.error("Run build_tree() first")
                return {}
            
            logger.info(f"Loading tree from {self.tree_path}")
            self.finrag.load(str(self.tree_path))
        
        logger.info(f"\nQuestion: {question}")
        logger.info(f"Retrieval method: {method}")
        logger.info(f"Top-k: {top_k}")
        logger.info(f"Using Pathway VectorStore for similarity search")
        
        # Query the system
        result = self.finrag.query(
            question=question,
            retrieval_method=method,
            top_k=top_k
        )
        
        # Display results
        if not quiet:
            print("\n" + "-" * 80)
            print("ANSWER")
            print("-" * 80)
            print(result.get('answer', 'No answer generated'))
            
            # Show retrieved nodes
            if 'retrieved_nodes' in result:
                print("\n" + "-" * 80)
                print(f"RETRIEVED NODES ({len(result['retrieved_nodes'])})")
                print("-" * 80)
                for i, node in enumerate(result['retrieved_nodes'], 1):
                    print(f"\n{i}. Node: {node['node_id']}")
                    print(f"   Level: {node['level']}")
                    print(f"   Score: {node['score']:.4f}")
                    print(f"   Preview: {node['text_preview']}")
            
            print("\n" + "=" * 80)
            print("QUERY COMPLETE")
            print("=" * 80)
        
        return result
    
    def query_enhanced(
        self,
        question: str,
        method: str = "collapsed_tree",
        top_k: int = 10,
        include_portfolio: bool = True,
        include_fundamentals: bool = True,
        quiet: bool = False
    ) -> Dict[str, Any]:
        """
        Enhanced query with multi-source context (portfolio + fundamentals + reports).
        
        This method automatically:
        1. Extracts tickers from the query
        2. Detects query intent
        3. Retrieves context from relevant sources
        4. Generates answer with enriched context
        
        Args:
            question: Question to ask
            method: Retrieval method for annual reports
            top_k: Number of results to retrieve from RAPTOR tree
            include_portfolio: Whether to include portfolio context
            include_fundamentals: Whether to include fundamental data
            quiet: If True, suppress console output (for orchestrator calls)
            
        Returns:
            Dictionary with answer, analysis, and metadata
        """
        if not quiet:
            print("\n" + "=" * 80)
            print("ENHANCED QUERY with Multi-Source Context")
            print("=" * 80)
        
        # Load tree if not already loaded
        if not self.finrag.tree.all_nodes:
            if not self.tree_path.exists():
                logger.error(f"No tree found at {self.tree_path}")
                logger.error("Run build_tree() first")
                return {}
            
            logger.info(f"Loading tree from {self.tree_path}")
            self.finrag.load(str(self.tree_path))
        
        logger.info(f"\nQuestion: {question}")
        
        # Step 1: Analyze query (extract tickers, detect intent)
        logger.info("\n[Step 1] Analyzing query...")
        query_analysis = self.multi_source_retriever.analyze_query(question)
        
        logger.info(f"  - Intent: {query_analysis['intent']}")
        logger.info(f"  - Tickers found: {query_analysis['tickers']}")
        if query_analysis['company_names']:
            logger.info(f"  - Companies: {query_analysis['company_names']}")
        logger.info(f"  - Portfolio stock: {query_analysis['is_portfolio_stock']}")
        
        # Override source requirements based on parameters
        if not include_portfolio:
            query_analysis['requires_portfolio'] = False
        if not include_fundamentals:
            query_analysis['requires_fundamentals'] = False
        
        # Step 2: Retrieve context from multiple sources
        logger.info("\n[Step 2] Retrieving context from sources...")
        logger.info(f"  - Annual Reports: {query_analysis['requires_annual_reports']}")
        logger.info(f"  - Fundamentals: {query_analysis['requires_fundamentals']}")
        logger.info(f"  - Portfolio: {query_analysis['requires_portfolio']}")
        
        # Get the RAPTOR retriever from finrag
        raptor_retriever = self.finrag.retriever if hasattr(self.finrag, 'retriever') else None
        
        context_result = self.multi_source_retriever.retrieve_context(
            query_analysis=query_analysis,
            raptor_retriever=raptor_retriever,
            top_k=top_k
        )
        
        logger.info(f"\n  ✓ Sources used: {', '.join(context_result['sources_used'])}")
        
        # Step 3: Generate answer with enriched context
        logger.info("\n[Step 3] Generating answer...")
        
        merged_context = context_result['merged_context']
        
        # Build enhanced prompt with source information
        enhanced_prompt = f"""Context from multiple sources:

{merged_context}

Question: {question}

Please provide a comprehensive answer using the information from the sources above. 
If information comes from the portfolio, mention the allocation details. 
If using fundamental metrics, cite the specific numbers.
If drawing from annual reports, reference the relevant sections."""
        
        answer_result = self.finrag.qa_model.answer_question(merged_context, question)
        
        # Display results
        if not quiet:
            print("\n" + "-" * 80)
            print("QUERY ANALYSIS")
            print("-" * 80)
            print(f"Intent: {query_analysis['intent']}")
            print(f"Tickers: {', '.join(query_analysis['tickers']) if query_analysis['tickers'] else 'None'}")
            print(f"Companies: {', '.join(query_analysis['company_names']) if query_analysis['company_names'] else 'None'}")
            print(f"Sources Used: {', '.join(context_result['sources_used'])}")
            
            print("\n" + "-" * 80)
            print("ANSWER")
            print("-" * 80)
            print(answer_result.get('answer', 'No answer generated'))
            
            # Show context preview
            print("\n" + "-" * 80)
            print("CONTEXT SOURCES")
            print("-" * 80)
            if 'portfolio' in context_result['sources_used']:
                print("✓ Portfolio context included")
            if 'fundamentals' in context_result['sources_used']:
                print(f"✓ Fundamental data for {len(context_result['context_sources']['fundamentals'])} ticker(s)")
            if 'annual_reports' in context_result['sources_used']:
                print("✓ Annual report excerpts included")
            
            print("\n" + "=" * 80)
            print("ENHANCED QUERY COMPLETE")
            print("=" * 80)
        
        return {
            'answer': answer_result.get('answer', ''),
            'query_analysis': query_analysis,
            'sources_used': context_result['sources_used'],
            'context': context_result['context_sources'],
            'retrieval_method': method,
            'tickers': query_analysis['tickers'],
            'intent': query_analysis['intent']
        }
    
    def chat(
        self,
        message: str,
        user_id: str = None,
        session_id: str = None,
        interactive: bool = False
    ) -> Dict[str, Any]:
        """
        Chat with the FinRAG system using the LLM orchestrator.
        
        The orchestrator automatically:
        1. Analyzes your query
        2. Decides which tool(s) to use (query, score, portfolio, etc.)
        3. Executes the tools
        4. Synthesizes a response
        
        Includes Langfuse tracing for usage tracking.
        
        Args:
            message: Your question or request
            user_id: Optional user ID for tracing
            session_id: Optional session ID for tracing
            interactive: If True, starts interactive chat loop
            
        Returns:
            Dictionary with answer and metadata
        """
        print("\n" + "=" * 80)
        print("🤖 FINRAG CHAT (Orchestrator Mode)")
        print("=" * 80)
        
        # Load tree if not already loaded
        if not self.finrag.tree.all_nodes:
            if not self.tree_path.exists():
                logger.error(f"No tree found at {self.tree_path}")
                logger.error("Run build_tree() first")
                return {}
            
            logger.info(f"Loading tree from {self.tree_path}")
            self.finrag.load(str(self.tree_path))
        
        # Initialize orchestrator
        logger.info("Initializing LLM Orchestrator...")
        orchestrator_config = OrchestratorConfig(
            routing_model="gpt-4o-mini",
            synthesis_model="gpt-4o-mini",
            max_tools_per_query=3,
            fallback_on_error=True
        )
        
        orchestrator = FinRAGOrchestrator(
            pipeline=self,
            config=orchestrator_config,
            memory_size=5  # Remember last 5 conversation turns
        )
        logger.info("✓ Orchestrator ready (with 5-turn memory)")
        
        if interactive:
            # Interactive chat loop
            print("\n💬 Interactive mode. Type 'quit' or 'exit' to stop.")
            print("   Type 'clear' to clear conversation history.")
            print("   Type 'history' to see conversation history.")
            print("-" * 80)
            
            while True:
                try:
                    # Show memory indicator
                    mem_count = len(orchestrator.conversation_history)
                    mem_indicator = f"[💾 {mem_count}/5]" if mem_count > 0 else ""
                    user_input = input(f"\n📝 You {mem_indicator}: ").strip()
                    
                    if user_input.lower() in ['quit', 'exit', 'q']:
                        print("\n👋 Goodbye!")
                        break
                    if not user_input:
                        continue
                    
                    # Handle special commands
                    if user_input.lower() == 'clear':
                        orchestrator.clear_history()
                        print("🗑️  Conversation history cleared.")
                        continue
                    
                    if user_input.lower() == 'history':
                        if orchestrator.conversation_history:
                            print("\n📜 Conversation History:")
                            print("-" * 40)
                            for i, turn in enumerate(orchestrator.conversation_history, 1):
                                print(f"{i}. You: {turn['user'][:100]}{'...' if len(turn['user']) > 100 else ''}")
                                print(f"   Bot: {turn['assistant'][:100]}{'...' if len(turn['assistant']) > 100 else ''}")
                        else:
                            print("📜 No conversation history yet.")
                        continue
                    
                    # Process message
                    result = orchestrator.chat(
                        query=user_input,
                        user_id=user_id,
                        session_id=session_id
                    )
                    
                    print(f"\n🤖 Assistant: {result.answer}")
                    print(f"\n   📊 Tools used: {', '.join(result.tools_used)}")
                    print(f"   ⏱️  Time: {result.total_time:.2f}s")
                    print(f"   💾 Memory: {len(orchestrator.conversation_history)}/5 turns")
                    if result.usage_stats:
                        total = result.usage_stats.get("total", {})
                        print(f"   🔢 Tokens: {total.get('total_tokens', 0):,} (prompt: {total.get('prompt_tokens', 0):,}, completion: {total.get('completion_tokens', 0):,})")
                        print(f"   💰 Cost: ${total.get('cost_usd', 0):.6f}")
                    
                except KeyboardInterrupt:
                    print("\n\n👋 Goodbye!")
                    break
            
            flush_langfuse()
            return {}
        
        # Single message mode
        print(f"\n📝 Message: {message}")
        print("-" * 80)
        
        result = orchestrator.chat(
            query=message,
            user_id=user_id,
            session_id=session_id
        )
        
        # Display results
        print("\n" + "-" * 80)
        print("🤖 ANSWER")
        print("-" * 80)
        print(result.answer)
        
        print("\n" + "-" * 80)
        print("📊 METADATA")
        print("-" * 80)
        print(f"Tools used: {', '.join(result.tools_used)}")
        print(f"Routing confidence: {result.routing_decision.confidence:.0%}")
        print(f"Reasoning: {result.routing_decision.reasoning}")
        print(f"Total time: {result.total_time:.2f}s")
        print(f"Success: {'✓' if result.success else '✗'}")
        
        # Display usage stats
        if result.usage_stats:
            print("\n" + "-" * 80)
            print("📈 USAGE & COST")
            print("-" * 80)
            total = result.usage_stats.get("total", {})
            routing = result.usage_stats.get("routing", {})
            synthesis = result.usage_stats.get("synthesis", {})
            
            print(f"Routing tokens:    {routing.get('total_tokens', 0):,} (prompt: {routing.get('prompt_tokens', 0):,}, completion: {routing.get('completion_tokens', 0):,})")
            print(f"Synthesis tokens:  {synthesis.get('total_tokens', 0):,} (prompt: {synthesis.get('prompt_tokens', 0):,}, completion: {synthesis.get('completion_tokens', 0):,})")
            print(f"Total tokens:      {total.get('total_tokens', 0):,}")
            print(f"")
            cost_breakdown = total.get("cost_breakdown", {})
            print(f"Input cost:        ${cost_breakdown.get('input_cost', 0):.6f}")
            print(f"Output cost:       ${cost_breakdown.get('output_cost', 0):.6f}")
            print(f"Total cost:        ${total.get('cost_usd', 0):.6f}")
        
        # Flush Langfuse traces
        flush_langfuse()
        
        print("\n" + "=" * 80)
        print("CHAT COMPLETE")
        print("=" * 80)
        
        return {
            'answer': result.answer,
            'tools_used': result.tools_used,
            'routing': result.routing_decision.to_dict(),
            'total_time': result.total_time,
            'success': result.success,
            'usage_stats': result.usage_stats
        }
    
    def evaluate(
        self,
        dataset_path: str = None,
        ground_truth: str = None,
        question: str = None,
        generate_testset: bool = False,
        testset_size: int = 10,
        output_path: str = None,
        evaluator_model: str = "gpt-4o-mini"
    ) -> Dict[str, Any]:
        """
        Evaluate RAG quality using RAGAS metrics.
        
        Supports four modes:
        1. Single question evaluation (--question + --ground-truth)
        2. Dataset evaluation (--eval-dataset)
        3. Synthetic testset generation (--generate-testset)
        4. Default evaluation with built-in questions
        
        Metrics computed:
        - Faithfulness: Is the answer grounded in context?
        - Answer Correctness: Is the answer factually correct?
        - Context Recall: Did we retrieve all relevant docs?
        - Context Precision: Of retrieved docs, how many are relevant?
        
        Args:
            dataset_path: Path to evaluation dataset (JSONL)
            ground_truth: Expected answer for single question evaluation
            question: Question for single evaluation
            generate_testset: Generate synthetic evaluation dataset
            testset_size: Number of samples for synthetic testset
            num_synthetic: Number of synthetic questions to generate
            output_path: Path to save results
            evaluator_model: Model for evaluation
            
        Returns:
            Dictionary with evaluation results
        """
        print("\n" + "=" * 80)
        print("📊 FINRAG EVALUATION (RAGAS)")
        print("=" * 80)
        
        try:
            from finrag.evaluation import (
                RAGASEvaluator, 
                EvaluationConfig,
                EvalDataset,
                EvalSample,
                load_eval_dataset,
                save_eval_dataset,
                create_finrag_eval_dataset
            )
        except ImportError as e:
            logger.error(f"Evaluation module not available: {e}")
            logger.error("Install with: pip install ragas langchain-openai")
            return {"error": str(e)}
        
        # Load tree if not already loaded
        if not self.finrag.tree.all_nodes:
            if not self.tree_path.exists():
                logger.error(f"No tree found at {self.tree_path}")
                logger.error("Run build_tree() first")
                return {}
            
            logger.info(f"Loading tree from {self.tree_path}")
            self.finrag.load(str(self.tree_path))
        
        # Define prediction function
        def predict_fn(q: str) -> Dict[str, Any]:
            """Get answer and contexts for a question."""
            result = self.finrag.query(
                question=q,
                retrieval_method="hybrid",  # Hybrid search for better recall
                top_k=70  # Increased to 70 for better coverage
            )
            
            # Extract contexts from retrieved nodes
            contexts = []
            if 'retrieved_nodes' in result:
                for node in result['retrieved_nodes']:
                    if 'text' in node:
                        contexts.append(node['text'])
                    elif 'text_preview' in node:
                        contexts.append(node['text_preview'])
            
            return {
                "answer": result.get("answer", ""),
                "contexts": contexts
            }
        
        # Determine evaluation mode
        if generate_testset:
            # Generate synthetic evaluation dataset
            print(f"\n🔧 Generating Synthetic Testset")
            print("-" * 60)
            print(f"   Target size: {testset_size} samples")
            
            try:
                from finrag.evaluation import TestsetGenerator
                
                # Get parsed documents path
                cache_dir = Path("cache/parsed_docs")
                if not cache_dir.exists():
                    logger.error("No parsed documents found. Run document parsing first.")
                    return {"error": "No parsed documents in cache/parsed_docs"}
                
                # Look for both .pkl and .txt files
                doc_paths = list(cache_dir.glob("*.pkl")) + list(cache_dir.glob("*.txt"))
                if not doc_paths:
                    logger.error("No parsed document files found in cache/parsed_docs")
                    return {"error": "No parsed documents found"}
                
                print(f"   Found {len(doc_paths)} parsed documents")
                
                # Generate testset
                generator = TestsetGenerator()
                dataset = generator.generate_from_parsed_docs(
                    doc_paths=[str(p) for p in doc_paths],
                    size=testset_size
                )
                
                if not dataset.samples:
                    logger.error("No samples were generated")
                    return {"error": "Failed to generate any evaluation samples"}
                
                # Save the generated dataset
                output_file = output_path or "eval_testset_generated.jsonl"
                save_eval_dataset(dataset, output_file)
                
                print(f"\n✅ Generated {len(dataset)} samples")
                print(f"   Saved to: {output_file}")
                print("\n📋 Sample questions generated:")
                for i, sample in enumerate(dataset.samples[:5]):
                    q_display = sample.question[:100] + "..." if len(sample.question) > 100 else sample.question
                    print(f"   {i+1}. {q_display}")
                
                if len(dataset) > 5:
                    print(f"   ... and {len(dataset) - 5} more")
                
                print("\n" + "=" * 80)
                print("💡 To evaluate using this testset, run:")
                print(f"   python main.py --mode evaluate --eval-dataset {output_file}")
                print("=" * 80)
                
                return {"dataset_path": output_file, "num_samples": len(dataset)}
                
            except ImportError as e:
                logger.error(f"RAGAS testset generation requires additional dependencies: {e}")
                logger.error("Install with: pip install ragas langchain-openai langchain-community")
                return {"error": str(e)}
            except Exception as e:
                logger.error(f"Testset generation failed: {e}")
                return {"error": str(e)}
        
        elif question and ground_truth:
            # Single question evaluation
            print(f"\n📝 Single Question Evaluation")
            print("-" * 60)
            print(f"Question: {question}")
            print(f"Ground Truth: {ground_truth}")
            
            config = EvaluationConfig(evaluator_model=evaluator_model)
            evaluator = RAGASEvaluator(config)
            
            # Get prediction
            prediction = predict_fn(question)
            
            print(f"\n🤖 Generated Answer:")
            print(prediction["answer"][:500] + "..." if len(prediction["answer"]) > 500 else prediction["answer"])
            print(f"\n📚 Contexts Retrieved: {len(prediction['contexts'])}")
            
            # Evaluate
            scores = evaluator.evaluate_single(
                question=question,
                ground_truth=ground_truth,
                answer=prediction["answer"],
                contexts=prediction["contexts"]
            )
            
            print("\n" + "-" * 60)
            print("📊 SCORES")
            print("-" * 60)
            for metric, score in scores.items():
                if isinstance(score, float):
                    print(f"  {metric}: {score:.4f}")
                else:
                    print(f"  {metric}: {score}")
            
            print("\n" + "=" * 80)
            return {"scores": scores, "answer": prediction["answer"]}
        
        elif dataset_path:
            # Dataset evaluation
            print(f"\n📂 Loading dataset from: {dataset_path}")
            dataset = load_eval_dataset(dataset_path)
        
        else:
            # Use default FinRAG evaluation dataset
            print(f"\n📋 Using default FinRAG evaluation dataset")
            dataset = create_finrag_eval_dataset()
        
        print(f"   Samples: {len(dataset)}")
        
        # Run evaluation
        config = EvaluationConfig(evaluator_model=evaluator_model)
        evaluator = RAGASEvaluator(config)
        
        print("\n🔄 Running evaluation...")
        print("-" * 60)
        
        results = evaluator.evaluate(
            dataset=dataset,
            predict_fn=predict_fn,
            show_progress=True
        )
        
        # Display results
        print("\n" + results.summary())
        
        # Save results if output path provided
        if output_path:
            import json
            output_data = {
                "results": results.to_dict(),
                "dataset_summary": dataset.summary(),
                "samples": [s.to_dict() for s in dataset.samples]
            }
            
            with open(output_path, 'w') as f:
                json.dump(output_data, f, indent=2)
            
            print(f"\n💾 Results saved to: {output_path}")
        
        # Also save evaluated dataset
        if dataset_path:
            evaluated_path = dataset_path.replace('.jsonl', '_evaluated.jsonl')
            save_eval_dataset(dataset, evaluated_path)
            print(f"💾 Evaluated dataset saved to: {evaluated_path}")
        
        print("\n" + "=" * 80)
        print("EVALUATION COMPLETE")
        print("=" * 80)
        
        return results.to_dict()
    
    def score_stock(
        self, 
        ticker: str, 
        company_name: str = None,
        ticker_suffix: str = "",
        save_output: bool = True
    ) -> Dict[str, Any]:
        """
        Score a stock using ensemble method (sentiment, trends, risk, quantitative, LLM).
        
        Args:
            ticker: Stock ticker symbol (e.g., "AAPL", "MSFT", "TCS")
            company_name: Company name for RAG queries (if None, uses ticker)
            ticker_suffix: Suffix for ticker (e.g., ".NS" for NSE, ".BO" for BSE)
            save_output: Whether to save the score to JSON
            
        Returns:
            Dictionary with comprehensive stock score
        """
        print("\n" + "=" * 80)
        print(f"SCORING STOCK: {ticker}{ticker_suffix}")
        print("=" * 80)
        
        # Load tree if not already loaded
        if not self.finrag.tree.all_nodes:
            if not self.tree_path.exists():
                logger.error(f"No tree found at {self.tree_path}")
                logger.error("Run build_tree() first")
                return {}
            
            logger.info(f"Loading tree from {self.tree_path}")
            self.finrag.load(str(self.tree_path))
        
        # Use ticker as company name if not provided
        if company_name is None:
            company_name = ticker
        
        logger.info(f"\nScoring {company_name} ({ticker}{ticker_suffix})...")
        logger.info("Using ensemble method with 5 components:")
        logger.info("  1. Sentiment Analysis (25%)")
        logger.info("  2. YoY Trends (20%)")
        logger.info("  3. Risk-Adjusted Score (20%)")
        logger.info("  4. Quantitative Metrics (20%)")
        logger.info("  5. LLM Judge (15%)")
        
        try:
            # Initialize ensemble scorer if not already done
            if self.ensemble_scorer is None:
                logger.info("Initializing ensemble scorer...")
                self.ensemble_scorer = EnsembleScorer(config=self.scoring_config)
            
            # Run ensemble scoring
            logger.info("\nRunning ensemble scoring (this may take 30-60 seconds)...")
            result = self.ensemble_scorer.score_company(
                finrag=self.finrag,
                ticker=ticker,
                company_name=company_name,
                ticker_suffix=ticker_suffix
            )
            
            # Cache fundamental data for future queries
            logger.info("\nCaching fundamental data for enhanced queries...")
            self._cache_fundamental_data_from_scoring(ticker, result)
            
            logger.info("✓ Scoring complete!")
            
            # Display results
            print("\n" + "-" * 80)
            print("FINAL SCORE")
            print("-" * 80)
            print(f"Score: {result.score:.1f}/100")
            print(f"Direction: {result.direction.upper()}")
            print(f"Confidence: {result.confidence:.1f}%")
            print(f"Time Horizon: {result.time_horizon}")
            
            # Recommendation
            if result.direction == "bullish" and result.confidence > 70:
                recommendation = "STRONG BUY"
            elif result.direction == "bullish":
                recommendation = "BUY"
            elif result.direction == "neutral" and result.score > 50:
                recommendation = "HOLD (Slight Positive)"
            elif result.direction == "neutral":
                recommendation = "HOLD"
            elif result.direction == "bearish" and result.confidence > 70:
                recommendation = "STRONG SELL"
            else:
                recommendation = "SELL"
            
            print(f"\nRecommendation: {recommendation}")
            
            # Component breakdown
            print("\n" + "-" * 80)
            print("COMPONENT SCORES")
            print("-" * 80)
            print(f"Sentiment Analysis:    {result.sentiment_score:.1f}/100 (25%)")
            print(f"YoY Trends:            {result.yoy_trend_score:.1f}/100 (20%)")
            print(f"Risk-Adjusted:         {result.risk_adjusted_score:.1f}/100 (20%)")
            print(f"Quantitative Metrics:  {result.quantitative_score:.1f}/100 (20%)")
            print(f"LLM Judge:             {result.llm_judge_score:.1f}/100 (15%)")
            
            # Quantitative breakdown
            print("\n" + "-" * 80)
            print("QUANTITATIVE BREAKDOWN")
            print("-" * 80)
            quant_breakdown = result.breakdown.get("quantitative", {}).get("breakdown", {})
            for category, score in quant_breakdown.items():
                print(f"{category.replace('_', ' ').title():.<30} {score:.1f}/100")
            
            # Save output
            if save_output:
                output_dir = Path("output")
                output_dir.mkdir(exist_ok=True)
                output_file = output_dir / f"{ticker}_score.json"
                
                with open(output_file, 'w') as f:
                    f.write(result.to_json())
                
                logger.info(f"\n✓ Results saved to: {output_file}")
            
            print("\n" + "=" * 80)
            print("SCORING COMPLETE")
            print("=" * 80)
            
            # Return as dictionary
            return {
                "ticker": ticker,
                "company_name": company_name,
                "score": result.score,
                "direction": result.direction,
                "confidence": result.confidence,
                "recommendation": recommendation,
                "component_scores": {
                    "sentiment": result.sentiment_score,
                    "yoy_trends": result.yoy_trend_score,
                    "risk_adjusted": result.risk_adjusted_score,
                    "quantitative": result.quantitative_score,
                    "llm_judge": result.llm_judge_score
                },
                "breakdown": result.breakdown
            }
            
        except Exception as e:
            logger.error(f"Error scoring {ticker}: {e}")
            import traceback
            traceback.print_exc()
            return {}
    
    def batch_score_stocks(
        self,
        tickers: List[Dict[str, str]],
        save_output: bool = True,
        output_file: str = "batch_scores.json"
    ) -> Dict[str, Any]:
        """
        Score multiple stocks in batch and return consolidated results.
        If annual reports are not available for a ticker, uses only yfinance data
        and LLM judging (skips RAG-based sentiment/trend analysis).
        
        Args:
            tickers: List of dicts with 'ticker', optional 'company_name', 'ticker_suffix'
                     Example: [
                         {"ticker": "AAPL", "company_name": "Apple"},
                         {"ticker": "TCS", "ticker_suffix": ".NS"},
                     ]
            save_output: Whether to save results to JSON file
            output_file: Output filename (in output/ directory)
            
        Returns:
            Dictionary with simplified scores: {ticker: {"score": X, "confidence": Y}}
        """
        print("\n" + "=" * 80)
        print(f"BATCH SCORING: {len(tickers)} STOCKS")
        print("=" * 80)
        
        # Load tree if not already loaded
        if not self.finrag.tree.all_nodes:
            if not self.tree_path.exists():
                logger.error(f"No tree found at {self.tree_path}")
                logger.error("Run build_tree() first")
                return {"error": "Tree not found"}
            
            logger.info(f"Loading tree from {self.tree_path}")
            self.finrag.load(str(self.tree_path))
        
        # Simplified results: {ticker: {"score": X, "confidence": Y}}
        scores = {}
        stats = {"with_reports": 0, "without_reports": 0, "failed": 0}
        
        for idx, ticker_info in enumerate(tickers, 1):
            ticker = ticker_info.get("ticker")
            company_name = ticker_info.get("company_name", ticker)
            ticker_suffix = ticker_info.get("ticker_suffix", "")
            
            print(f"\n[{idx}/{len(tickers)}] Processing {ticker}{ticker_suffix}...")
            
            try:
                # Check if annual reports exist for this company
                has_reports = self._check_company_reports_exist(company_name, ticker)
                
                if has_reports:
                    print(f"  ✓ Annual reports found for {company_name}")
                    stats["with_reports"] += 1
                    
                    # Full scoring with RAG
                    score_result = self.score_stock(
                        ticker=ticker,
                        company_name=company_name,
                        ticker_suffix=ticker_suffix,
                        save_output=False
                    )
                    
                    if score_result:
                        scores[ticker] = {
                            "score": round(score_result["score"], 2),
                            "confidence": round(score_result["confidence"], 2)
                        }
                        logger.info(f"  ✓ {ticker}: {score_result['score']:.1f}/100 (confidence: {score_result['confidence']:.1f}%)")
                    else:
                        stats["failed"] += 1
                        scores[ticker] = {"score": None, "confidence": None, "error": "Scoring failed"}
                else:
                    print(f"  ⚠ No annual reports for {company_name} - using yfinance + LLM only")
                    stats["without_reports"] += 1
                    
                    # Simplified scoring without RAG
                    simplified_result = self._score_without_reports(
                        ticker=ticker,
                        company_name=company_name,
                        ticker_suffix=ticker_suffix
                    )
                    
                    if simplified_result:
                        scores[ticker] = {
                            "score": round(simplified_result["score"], 2),
                            "confidence": round(simplified_result["confidence"], 2)
                        }
                        logger.info(f"  ✓ {ticker}: {simplified_result['score']:.1f}/100 (confidence: {simplified_result['confidence']:.1f}%) [no reports]")
                    else:
                        stats["failed"] += 1
                        scores[ticker] = {"score": None, "confidence": None, "error": "Scoring failed"}
                    
            except Exception as e:
                stats["failed"] += 1
                logger.error(f"  ✗ {ticker}: {str(e)}")
                scores[ticker] = {"score": None, "confidence": None, "error": str(e)}
        
        # Save simplified output
        if save_output:
            output_dir = Path("output")
            output_dir.mkdir(exist_ok=True)
            output_path = output_dir / output_file
            
            with open(output_path, 'w') as f:
                json.dump(scores, f, indent=2)
            
            logger.info(f"\n✓ Batch scores saved to: {output_path}")
        
        # Print summary
        print("\n" + "=" * 80)
        print("BATCH SCORING SUMMARY")
        print("=" * 80)
        print(f"Total Stocks:        {len(tickers)}")
        print(f"With Annual Reports: {stats['with_reports']}")
        print(f"Without Reports:     {stats['without_reports']}")
        print(f"Failed:              {stats['failed']}")
        
        valid_scores = [v["score"] for v in scores.values() if v.get("score") is not None]
        if valid_scores:
            print(f"Average Score:       {sum(valid_scores) / len(valid_scores):.1f}/100")
            
            # Top 5 stocks
            sorted_stocks = sorted(
                [(k, v) for k, v in scores.items() if v.get("score") is not None],
                key=lambda x: x[1]["score"],
                reverse=True
            )[:5]
            print(f"\nTop 5 Stocks:")
            for i, (tick, data) in enumerate(sorted_stocks, 1):
                print(f"  {i}. {tick}: {data['score']:.1f}/100 (confidence: {data['confidence']:.1f}%)")
        
        print("=" * 80)
        
        return scores
    
    def _check_company_reports_exist(self, company_name: str, ticker: str) -> bool:
        """
        Check if annual reports exist for a company in the tree.
        Does a quick query to see if relevant documents are found.
        """
        try:
            # Try a simple query to check if documents exist
            test_query = f"How is {company_name}'s performance?"
            result = self.finrag.query(
                question=test_query,
                retrieval_method="collapsed_tree",
                top_k=5
            )
            
            # Check if we got meaningful content (not just "I don't have information")
            answer = result.get("answer", "").lower()
            nodes = result.get("retrieved_nodes", [])
            
            # If we have retrieved nodes and the answer doesn't indicate no data
            if nodes and len(nodes) > 0:
                # Check if answer indicates data was found
                no_data_phrases = [
                    "i don't have",
                    "no information",
                    "not available",
                    "cannot find",
                    "don't have access",
                    "no data"
                ]
                if not any(phrase in answer for phrase in no_data_phrases):
                    return True
            
            return False
            
        except Exception as e:
            logger.warning(f"Error checking reports for {company_name}: {e}")
            return False
    
    def _score_without_reports(
        self,
        ticker: str,
        company_name: str,
        ticker_suffix: str
    ) -> Optional[Dict[str, Any]]:
        """
        Score a stock using only yfinance data and LLM judging (no RAG).
        Used when annual reports are not available.
        """
        from src.finrag.scoring.financial_data_fetcher import FinancialDataFetcher
        from src.finrag.scoring.quantitative_scorer import QuantitativeScorer
        
        try:
            yf_ticker = f"{ticker}{ticker_suffix}"
            
            # 1. Fetch financial data from yfinance
            fetcher = FinancialDataFetcher()
            financial_data = fetcher.get_company_data(yf_ticker)
            
            if not company_name:
                company_name = financial_data.get("company_name", ticker)
            
            # 2. Quantitative scoring (from yfinance data)
            quant_scorer = QuantitativeScorer()
            quant_result = quant_scorer.score_financial_data(financial_data)
            quant_score = quant_result["score"]
            
            # 3. LLM Judge assessment (without RAG context)
            llm_result = self._llm_judge_without_rag(
                ticker=ticker,
                company_name=company_name,
                financial_data=financial_data,
                quant_result=quant_result
            )
            llm_score = llm_result["score"]
            
            # Calculate final score (60% quantitative, 40% LLM judge)
            # Higher weight on quantitative since we don't have qualitative data
            final_score = quant_score * 0.6 + llm_score * 0.4
            
            # Confidence is lower without annual reports
            base_confidence = (quant_result.get("confidence", 50) + llm_result.get("confidence", 50)) / 2
            confidence = base_confidence * 0.7  # 30% penalty for no reports
            
            return {
                "score": final_score,
                "confidence": confidence,
                "has_annual_reports": False,
                "component_scores": {
                    "quantitative": quant_score,
                    "llm_judge": llm_score
                }
            }
            
        except Exception as e:
            logger.error(f"Error in simplified scoring for {ticker}: {e}")
            return None
    
    def _llm_judge_without_rag(
        self,
        ticker: str,
        company_name: str,
        financial_data: Dict[str, Any],
        quant_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        LLM judge assessment using only yfinance data (no RAG context).
        """
        import openai
        
        client = openai.OpenAI()
        
        # Format financial data for LLM
        metrics_summary = []
        key_metrics = [
            ("P/E Ratio", "pe_ratio"),
            ("P/B Ratio", "pb_ratio"),
            ("Profit Margin", "profit_margin"),
            ("ROE", "roe"),
            ("ROA", "roa"),
            ("Debt/Equity", "debt_to_equity"),
            ("Current Ratio", "current_ratio"),
            ("Revenue Growth", "revenue_growth"),
            ("Earnings Growth", "earnings_growth"),
            ("Dividend Yield", "dividend_yield"),
        ]
        
        for name, key in key_metrics:
            value = financial_data.get(key)
            if value is not None:
                if "Ratio" in name or "Yield" in name:
                    metrics_summary.append(f"- {name}: {value:.2f}")
                elif "Growth" in name or "Margin" in name or key in ["roe", "roa"]:
                    metrics_summary.append(f"- {name}: {value*100:.1f}%")
                else:
                    metrics_summary.append(f"- {name}: {value:.2f}")
        
        metrics_text = "\n".join(metrics_summary) if metrics_summary else "Limited financial data available"
        
        prompt = f"""You are a financial analyst evaluating {company_name} ({ticker}) based on available financial metrics.

Note: Annual reports are NOT available for this company, so base your assessment ONLY on the following financial data from yfinance:

{metrics_text}

Sector: {financial_data.get('sector', 'Unknown')}
Industry: {financial_data.get('industry', 'Unknown')}
Market Cap: {financial_data.get('market_cap', 'Unknown')}

Quantitative Score: {quant_result['score']:.1f}/100

Based on these metrics alone, provide:
1. An investment score from 0-100 (where 50 is neutral)
2. A confidence level (0-100%) in your assessment
3. Key observations (2-3 points)

Respond in JSON format:
{{
    "score": <0-100>,
    "confidence": <0-100>,
    "observations": ["point1", "point2", "point3"]
}}
"""
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a financial analyst. Respond only with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=300
            )
            
            response_text = response.choices[0].message.content.strip()
            
            # Clean up response
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
            response_text = response_text.strip()
            
            result = json.loads(response_text)
            
            return {
                "score": result.get("score", 50),
                "confidence": result.get("confidence", 50),
                "observations": result.get("observations", [])
            }
            
        except Exception as e:
            logger.warning(f"LLM judge error: {e}")
            return {"score": 50, "confidence": 30, "observations": ["Error in LLM assessment"]}
    
    def _get_pdf_hash(self, pdf_path: str) -> str:
        """Get hash of PDF file for caching."""
        with open(pdf_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    
    def _get_cache_path(self, pdf_path: str) -> Path:
        """Get cache file path for a PDF."""
        pdf_hash = self._get_pdf_hash(pdf_path)
        pdf_name = Path(pdf_path).stem
        return self.cache_dir / f"{pdf_name}_{pdf_hash}.txt"
    
    def _load_or_parse_pdf(self, pdf_path: str) -> str:
        """Load parsed text from cache or parse the PDF."""
        cache_path = self._get_cache_path(pdf_path)
        
        # Try loading from cache
        if cache_path.exists():
            logger.info(f"  📦 Loading from cache...")
            with open(cache_path, 'r', encoding='utf-8') as f:
                return f.read()
        
        # Parse PDF
        logger.info(f"  🔄 Parsing PDF...")
        text = self.finrag.load_pdf(pdf_path)
        
        # Save to cache
        with open(cache_path, 'w', encoding='utf-8') as f:
            f.write(text)
        logger.info(f"  💾 Cached for future use")
        
        return text
    
    def _cache_fundamental_data_from_scoring(
        self,
        ticker: str,
        scoring_result: Any
    ) -> None:
        """
        Extract and cache fundamental data from scoring results.
        
        Args:
            ticker: Stock ticker
            scoring_result: Result from ensemble scoring
        """
        try:
            fundamental_data = {
                'financial_metrics': {},
                'sentiment_analysis': {},
                'risk_factors': [],
                'opportunities': []
            }
            
            # Extract from breakdown
            breakdown = scoring_result.breakdown if hasattr(scoring_result, 'breakdown') else {}
            
            # Quantitative metrics
            if 'quantitative' in breakdown:
                quant = breakdown['quantitative']
                if 'breakdown' in quant:
                    fundamental_data['financial_metrics'] = quant['breakdown']
            
            # Sentiment data
            if 'sentiment' in breakdown:
                sentiment = breakdown['sentiment']
                fundamental_data['sentiment_analysis'] = {
                    'overall_sentiment': scoring_result.direction if hasattr(scoring_result, 'direction') else 'neutral',
                    'sentiment_score': scoring_result.sentiment_score if hasattr(scoring_result, 'sentiment_score') else 0,
                    'details': sentiment
                }
            
            # Cache the data
            self.fundamental_cache.set(ticker, fundamental_data)
            logger.info(f"  ✓ Cached fundamental data for {ticker}")
            
        except Exception as e:
            logger.warning(f"Could not cache fundamental data for {ticker}: {e}")
    
    def run_full_pipeline(
        self, 
        ticker: str = "AAPL",
        company_name: str = None,
        ticker_suffix: str = ""
    ) -> None:
        """
        Run the complete pipeline: build → query → score.
        
        Args:
            ticker: Stock ticker to score
            company_name: Company name (defaults to ticker)
            ticker_suffix: Ticker suffix for exchanges
        """
        print("\n" + "=" * 80)
        print("RUNNING FULL FINRAG PIPELINE")
        print("=" * 80)
        print(f"\nTarget: {ticker}{ticker_suffix}")
        print("Pipeline: Build Tree → Query System → Score Stock")
        print("=" * 80)
        
        if company_name is None:
            company_name = ticker
        
        # Step 1: Build tree
        self.build_tree()
        
        # Step 2: Sample queries
        questions = [
            f"What is the latest information about {company_name}?",
            f"What are the financial metrics for {company_name}?",
            f"What are the risks for {company_name}?"
        ]
        
        for question in questions:
            self.query(question)
        
        # Step 3: Score stock
        self.score_stock(ticker, company_name, ticker_suffix)
        
        print("\n" + "=" * 80)
        print("FULL PIPELINE COMPLETE")
        print("=" * 80)


def main():
    """Main entry point with CLI argument parsing."""
    parser = argparse.ArgumentParser(
        description="FinRAG - Financial RAG System with Pathway VectorStore"
    )
    
    parser.add_argument(
        "--mode",
        type=str,
        choices=["build", "update", "update-file", "query", "query-enhanced", "chat", "chat-interactive", "score", "evaluate", "all"],
        default="all",
        help="Operation mode (update-file adds single file, chat uses LLM orchestrator, evaluate runs RAGAS metrics)"
    )
    
    parser.add_argument(
        "--tree-path",
        type=str,
        default="finrag_tree",
        help="Path to save/load the tree"
    )
    
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data",
        help="Directory containing PDF documents"
    )
    parser.add_argument(
        "--new-data-dir",
        type=str,
        default="update_data",
        help="Directory containing new PDF documents"
    )
    parser.add_argument(
        "--file-path",
        type=str,
        help="Path to single PDF file (for update-file mode)"
    )
    parser.add_argument(
        "--question",
        type=str,
        help="Question to query (for query mode)"
    )
    
    parser.add_argument(
        "--ticker",
        type=str,
        default="HEROMOTOCO",
        help="Stock ticker to score (for score mode)"
    )
    
    parser.add_argument(
        "--company-name",
        type=str,
        help="Company name for RAG queries (defaults to ticker)"
    )
    
    parser.add_argument(
        "--ticker-suffix",
        type=str,
        default=".NS",
        help="Ticker suffix (e.g., '.NS' for NSE, '.BO' for BSE)"
    )
    
    parser.add_argument(
        "--force-rebuild",
        action="store_true",
        help="Force rebuild even if tree exists",
        default=True
    )
    
    parser.add_argument(
        "--retrieval-method",
        type=str,
        default="tree_traversal",
        help="Retrieval method for queries"
    )
    
    parser.add_argument(
        "--top-k",
        type=int,
        default=60,
        help="Number of results to retrieve"
    )
    
    parser.add_argument(
        "--include-portfolio",
        action="store_true",
        default=True,
        help="Include portfolio context in enhanced queries"
    )
    
    parser.add_argument(
        "--include-fundamentals",
        action="store_true",
        default=True,
        help="Include fundamental data in enhanced queries"
    )
    
    # Chat mode arguments
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run chat mode in interactive loop"
    )
    
    parser.add_argument(
        "--user-id",
        type=str,
        default="cli_user",
        help="User ID for Langfuse tracing"
    )
    
    parser.add_argument(
        "--session-id",
        type=str,
        help="Session ID for Langfuse tracing (auto-generated if not provided)"
    )
    
    # Evaluation mode arguments
    parser.add_argument(
        "--eval-dataset",
        type=str,
        help="Path to evaluation dataset (JSONL) for evaluate mode"
    )
    
    parser.add_argument(
        "--ground-truth",
        type=str,
        help="Expected answer for single question evaluation"
    )
    
    parser.add_argument(
        "--eval-output",
        type=str,
        help="Path to save evaluation results (JSON)"
    )
    
    parser.add_argument(
        "--evaluator-model",
        type=str,
        default="gpt-4o-mini",
        help="Model for RAGAS evaluation"
    )
    
    parser.add_argument(
        "--generate-testset",
        action="store_true",
        help="Generate synthetic evaluation dataset from documents"
    )
    
    parser.add_argument(
        "--testset-size",
        type=int,
        default=10,
        help="Number of samples to generate for synthetic testset (default: 10)"
    )
    
    args = parser.parse_args()
    
    # Initialize pipeline
    pipeline = FinRAGPipeline(
        tree_path=args.tree_path,
        data_dir=args.data_dir
    )
    
    # Execute based on mode
    if args.mode == "build":
        pipeline.build_tree(force_rebuild=args.force_rebuild)
    
    elif args.mode == "update":
        pipeline.update_tree(new_data_dir=args.new_data_dir)
    
    elif args.mode == "update-file":
        if not args.file_path:
            print("Error: --file-path required for update-file mode")
            sys.exit(1)
        pipeline.update_tree_file(file_path=args.file_path)
    
    elif args.mode == "query":
        if not args.question:
            print("Error: --question required for query mode")
            sys.exit(1)
        pipeline.query(
            args.question,
            method=args.retrieval_method,
            top_k=args.top_k
        )
    
    elif args.mode == "query-enhanced":
        if not args.question:
            print("Error: --question required for query-enhanced mode")
            sys.exit(1)
        pipeline.query_enhanced(
            args.question,
            method=args.retrieval_method,
            top_k=args.top_k,
            include_portfolio=args.include_portfolio,
            include_fundamentals=args.include_fundamentals
        )
    
    elif args.mode == "score":
        pipeline.score_stock(
            args.ticker,
            company_name=args.company_name,
            ticker_suffix=args.ticker_suffix
        )
    
    elif args.mode == "chat":
        if not args.question and not args.interactive:
            print("Error: --question required for chat mode (or use --interactive)")
            sys.exit(1)
        pipeline.chat(
            message=args.question,
            interactive=args.interactive,
            user_id=args.user_id,
            session_id=args.session_id
        )
    
    elif args.mode == "chat-interactive":
        # Shortcut for interactive chat mode
        pipeline.chat(
            message="",
            interactive=True,
            user_id=args.user_id,
            session_id=args.session_id
        )
    
    elif args.mode == "evaluate":
        pipeline.evaluate(
            dataset_path=args.eval_dataset,
            ground_truth=args.ground_truth,
            question=args.question,
            generate_testset=args.generate_testset,
            testset_size=args.testset_size,
            output_path=args.eval_output,
            evaluator_model=args.evaluator_model
        )
    
    elif args.mode == "all":
        pipeline.run_full_pipeline(args.ticker)


if __name__ == "__main__":
    main()
