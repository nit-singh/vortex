"""
Build FinRAG tree once using all PDFs in the data folder.
This script should be run once to create the tree, then all other scripts can load it.
"""
import os
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Load environment variables from .env file
from finrag.utils import load_env_file
load_env_file()

from finrag import FinRAGConfig, FinRAG


def build_tree_from_all_pdfs():
    """Build FinRAG tree using all PDFs in the data folder."""
    
    # Initialize config
    config = FinRAGConfig()
    config.use_metadata_clustering = True  # Enable metadata-based clustering
    
    # Initialize FinRAG
    print("=" * 80)
    print("BUILDING FINRAG TREE FROM ALL PDFs")
    print("=" * 80)
    print("\nInitializing FinRAG system...")
    finrag = FinRAG(config)
    
    # Get all PDFs from data folder
    data_dir = Path(__file__).parent.parent / "data"
    pdf_files = list(data_dir.glob("*.pdf"))
    
    if not pdf_files:
        print(f"\n❌ No PDF files found in {data_dir}")
        print("Please add PDF files to the data folder and try again.")
        return False
    
    print(f"\n✓ Found {len(pdf_files)} PDF files:")
    for pdf in pdf_files:
        print(f"  - {pdf.name}")
    
    # Process all PDFs
    all_documents = []
    print("\n" + "=" * 80)
    print("PROCESSING PDFs")
    print("=" * 80)
    
    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"\n[{i}/{len(pdf_files)}] Processing: {pdf_path.name}")
        print("-" * 80)
        
        try:
            # Load PDF with filtering if enabled
            use_filtering = getattr(config, 'use_filtered_parsing', False)
            if use_filtering:
                print("  Using filtered parsing to extract key sections...")
            
            text = finrag.load_pdf(str(pdf_path))
            print(f"  ✓ Loaded {len(text):,} characters")
            
            all_documents.append(text)
            
        except Exception as e:
            print(f"  ❌ Error processing {pdf_path.name}: {e}")
            print(f"     Skipping this file...")
            continue
    
    if not all_documents:
        print("\n❌ No documents were successfully processed!")
        return False
    
    print(f"\n✓ Successfully processed {len(all_documents)}/{len(pdf_files)} PDFs")
    
    # Build the tree
    print("\n" + "=" * 80)
    print("BUILDING RAPTOR TREE")
    print("=" * 80)
    print("\nThis may take several minutes depending on the number of documents...")
    
    try:
        finrag.add_documents(all_documents)
        print("\n✓ Tree built successfully!")
    except Exception as e:
        print(f"\n❌ Error building tree: {e}")
        return False
    
    # Print statistics
    print("\n" + "=" * 80)
    print("TREE STATISTICS")
    print("=" * 80)
    
    stats = finrag.get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # Save the tree
    save_path = Path(__file__).parent.parent / "finrag_tree"
    print("\n" + "=" * 80)
    print("SAVING TREE")
    print("=" * 80)
    print(f"\nSaving to: {save_path}")
    
    try:
        finrag.save(str(save_path))
        print(f"✓ Tree saved successfully to {save_path}")
    except Exception as e:
        print(f"❌ Error saving tree: {e}")
        return False
    
    # Summary
    print("\n" + "=" * 80)
    print("BUILD COMPLETE!")
    print("=" * 80)
    print(f"""
✓ Processed {len(all_documents)} documents
✓ Built RAPTOR tree with {stats.get('total_nodes', 'N/A')} nodes
✓ Tree saved to: {save_path}

You can now use this tree in your applications by loading it:

    from finrag import FinRAG, FinRAGConfig
    
    config = FinRAGConfig()
    finrag = FinRAG(config)
    finrag.load("{save_path}")
    
    # Now query the system
    result = finrag.query("Your question here")

To rebuild the tree with updated PDFs, run this script again:
    python scripts/build_tree.py
""")
    
    return True


if __name__ == "__main__":
    success = build_tree_from_all_pdfs()
    sys.exit(0 if success else 1)
