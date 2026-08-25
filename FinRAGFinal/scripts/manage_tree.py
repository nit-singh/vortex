"""
FinRAG Tree Management CLI

Simple command-line tool to manage FinRAG trees.
"""
import sys
import argparse
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from finrag.utils import load_env_file
load_env_file()

from finrag import FinRAG, FinRAGConfig

# Rich formatting imports
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table
from rich.markdown import Markdown
from rich import box

console = Console()


def build_tree(data_dir: str = None, output_dir: str = None, use_filtering: bool = True):
    """Build tree from PDFs in data directory."""
    if data_dir is None:
        data_dir = Path(__file__).parent.parent / "data"
    else:
        data_dir = Path(data_dir)
    
    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "finrag_tree"
    else:
        output_dir = Path(output_dir)
    
    # Header
    console.print(Panel.fit(
        "[bold cyan]BUILDING FINRAG TREE[/bold cyan]",
        border_style="cyan",
        padding=(1, 2)
    ))
    
    # Configuration table
    config_table = Table(show_header=False, box=box.ROUNDED)
    config_table.add_row("[cyan]Data Directory[/cyan]", str(data_dir))
    config_table.add_row("[cyan]Output Directory[/cyan]", str(output_dir))
    config_table.add_row("[cyan]Filtered Parsing[/cyan]", "✓ Enabled" if use_filtering else "✗ Disabled")
    console.print(config_table)
    console.print()
    
    # Get PDFs
    pdf_files = list(data_dir.glob("*.pdf"))
    if not pdf_files:
        console.print(f"[red]✗ No PDF files found in {data_dir}[/red]")
        return False
    
    console.print(f"[green]✓[/green] Found [bold]{len(pdf_files)}[/bold] PDF files:")
    for pdf in pdf_files:
        console.print(f"  • {pdf.name}")
    console.print()
    
    # Initialize FinRAG
    config = FinRAGConfig()
    config.use_filtered_parsing = use_filtering
    config.use_metadata_clustering = True
    
    finrag = FinRAG(config)
    
    # Process PDFs with progress
    console.print(Panel("[bold yellow]Processing PDFs[/bold yellow]", border_style="yellow"))
    all_documents = []
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Processing PDFs...", total=len(pdf_files))
        
        for i, pdf_path in enumerate(pdf_files, 1):
            progress.update(task, description=f"[cyan]Processing: {pdf_path.name}")
            try:
                text = finrag.load_pdf(str(pdf_path))
                all_documents.append(text)
                console.print(f"  [green]✓[/green] {pdf_path.name}: {len(text):,} characters")
            except Exception as e:
                console.print(f"  [red]✗[/red] {pdf_path.name}: {str(e)}")
            progress.advance(task)
    
    if not all_documents:
        console.print("\n[red]✗ No documents were successfully processed[/red]")
        return False
    
    console.print()
    console.print(f"[green]✓[/green] Successfully processed [bold]{len(all_documents)}/{len(pdf_files)}[/bold] PDFs")
    
    # Build tree
    console.print(Panel("[bold yellow]Building RAPTOR Tree[/bold yellow]", border_style="yellow"))
    
    with console.status("[bold cyan]Building tree (this may take a few minutes)..."):
        try:
            finrag.add_documents(all_documents)
            console.print("[green]✓[/green] Tree built successfully")
        except Exception as e:
            console.print(f"[red]✗ Error building tree: {e}[/red]")
            return False
    
    # Save tree
    console.print()
    with console.status(f"[bold cyan]Saving to {output_dir}..."):
        try:
            finrag.save(str(output_dir))
            console.print(f"[green]✓[/green] Tree saved successfully")
        except Exception as e:
            console.print(f"[red]✗ Error saving tree: {e}[/red]")
            return False
    
    # Stats
    stats = finrag.get_statistics()
    console.print()
    stats_table = Table(title="📊 Tree Statistics", box=box.ROUNDED, border_style="green")
    stats_table.add_column("Metric", style="cyan")
    stats_table.add_column("Value", style="yellow", justify="right")
    
    for key, value in stats.items():
        if key != "levels":
            stats_table.add_row(key.replace("_", " ").title(), str(value))
    
    console.print(stats_table)
    
    # Success panel
    console.print()
    console.print(Panel.fit(
        "[bold green]✓ BUILD COMPLETE![/bold green]\n\n"
        f"Tree saved to: [cyan]{output_dir}[/cyan]\n"
        "Ready to query!",
        border_style="green",
        padding=(1, 2)
    ))
    return True


def show_stats(tree_dir: str = None):
    """Show statistics for a saved tree."""
    if tree_dir is None:
        tree_dir = Path(__file__).parent.parent / "finrag_tree"
    else:
        tree_dir = Path(tree_dir)
    
    if not tree_dir.exists():
        console.print(f"[red]✗ Tree not found at: {tree_dir}[/red]")
        return False
    
    # Header
    console.print(Panel.fit(
        "[bold cyan]TREE STATISTICS[/bold cyan]",
        border_style="cyan",
        padding=(1, 2)
    ))
    
    console.print(f"[cyan]Tree location:[/cyan] {tree_dir}")
    console.print()
    
    # Load tree
    config = FinRAGConfig()
    finrag = FinRAG(config)
    
    try:
        with console.status("[bold cyan]Loading tree..."):
            finrag.load(str(tree_dir))
        console.print("[green]✓[/green] Tree loaded successfully")
        console.print()
    except Exception as e:
        console.print(f"[red]✗ Error loading tree: {e}[/red]")
        return False
    
    # Show stats
    stats = finrag.get_statistics()
    
    # Main statistics table
    stats_table = Table(title="📊 Tree Overview", box=box.DOUBLE_EDGE, border_style="cyan")
    stats_table.add_column("Metric", style="cyan", no_wrap=True)
    stats_table.add_column("Value", style="yellow", justify="right")
    
    for key, value in stats.items():
        if key != "levels":
            display_name = key.replace("_", " ").title()
            stats_table.add_row(display_name, str(value))
    
    console.print(stats_table)
    
    # Levels breakdown if available
    if "levels" in stats:
        console.print()
        levels_table = Table(title="📈 Nodes per Level", box=box.ROUNDED, border_style="green")
        levels_table.add_column("Level", style="cyan", justify="center")
        levels_table.add_column("Node Count", style="yellow", justify="right")
        levels_table.add_column("Description", style="white")
        
        level_descriptions = {
            0: "Leaf nodes (original chunks)",
            1: "First clustering level",
            2: "Second clustering level",
            3: "Third clustering level",
            4: "Root level (highest summary)"
        }
        
        for level, count in sorted(stats["levels"].items()):
            desc = level_descriptions.get(level, f"Level {level}")
            levels_table.add_row(str(level), str(count), desc)
        
        console.print(levels_table)
    
    return True


def query_tree(question: str, tree_dir: str = None, method: str = "tree_traversal"):
    """Query a saved tree."""
    if tree_dir is None:
        tree_dir = Path(__file__).parent.parent / "finrag_tree"
    else:
        tree_dir = Path(tree_dir)
    
    if not tree_dir.exists():
        console.print(f"[red]✗ Tree not found at: {tree_dir}[/red]")
        return False
    
    # Header
    console.print(Panel.fit(
        "[bold cyan]QUERYING FINRAG TREE[/bold cyan]",
        border_style="cyan",
        padding=(1, 2)
    ))
    
    # Query info table
    query_table = Table(show_header=False, box=box.ROUNDED)
    query_table.add_row("[cyan]Tree Location[/cyan]", str(tree_dir))
    query_table.add_row("[cyan]Question[/cyan]", question)
    query_table.add_row("[cyan]Retrieval Method[/cyan]", method)
    console.print(query_table)
    console.print()
    
    # Load tree
    config = FinRAGConfig()
    finrag = FinRAG(config)
    
    try:
        with console.status("[bold cyan]Loading tree..."):
            finrag.load(str(tree_dir))
        console.print("[green]✓[/green] Tree loaded")
        console.print()
    except Exception as e:
        console.print(f"[red]✗ Error loading tree: {e}[/red]")
        return False
    
    # Query
    try:
        with console.status("[bold cyan]Analyzing documents and generating answer..."):
            result = finrag.query(question, retrieval_method=method)
        
        console.print("[green]✓[/green] Answer generated")
        console.print()
        
        # Display answer in a beautiful panel
        console.print(Panel(
            result['answer'],
            title="[bold green]💡 Answer[/bold green]",
            border_style="green",
            padding=(1, 2),
            expand=False
        ))
        
        console.print()
        
        # Retrieval information
        retrieval_table = Table(title="📚 Retrieval Information", box=box.ROUNDED, border_style="blue")
        retrieval_table.add_column("Metric", style="cyan")
        retrieval_table.add_column("Value", style="yellow")
        
        retrieval_table.add_row("Nodes Retrieved", str(len(result['retrieved_nodes'])))
        retrieval_table.add_row("Retrieval Method", result['retrieval_method'])
        
        console.print(retrieval_table)
        console.print()
        
        # Top retrieved nodes
        if result['retrieved_nodes']:
            nodes_table = Table(
                title="🎯 Top Retrieved Nodes",
                box=box.ROUNDED,
                border_style="magenta"
            )
            nodes_table.add_column("Rank", style="cyan", justify="center")
            nodes_table.add_column("Level", style="yellow", justify="center")
            nodes_table.add_column("Score", style="green", justify="right")
            nodes_table.add_column("Preview", style="white")
            
            for i, node in enumerate(result['retrieved_nodes'][:5], 1):
                preview = node['text_preview'][:80] + "..." if len(node['text_preview']) > 80 else node['text_preview']
                nodes_table.add_row(
                    str(i),
                    str(node['level']),
                    f"{node['score']:.3f}",
                    preview
                )
            
            console.print(nodes_table)
        
        return True
        
    except Exception as e:
        console.print(f"[red]✗ Error querying: {e}[/red]")
        return False


def main():
    """Main CLI function."""
    parser = argparse.ArgumentParser(
        description="FinRAG Tree Management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Build tree from data/ folder
  python manage_tree.py build
  
  # Build with custom directories
  python manage_tree.py build --data-dir ./my_pdfs --output-dir ./my_tree
  
  # Show tree statistics
  python manage_tree.py stats
  
  # Query the tree
  python manage_tree.py query "What is the revenue?"
  
  # Query with specific method
  python manage_tree.py query "What is the revenue?" --method collapsed_tree
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Build command
    build_parser = subparsers.add_parser('build', help='Build tree from PDFs')
    build_parser.add_argument('--data-dir', help='Directory containing PDF files')
    build_parser.add_argument('--output-dir', help='Directory to save tree')
    build_parser.add_argument('--no-filtering', action='store_true', 
                             help='Disable filtered parsing')
    
    # Stats command
    stats_parser = subparsers.add_parser('stats', help='Show tree statistics')
    stats_parser.add_argument('--tree-dir', help='Tree directory')
    
    # Query command
    query_parser = subparsers.add_parser('query', help='Query the tree')
    query_parser.add_argument('question', help='Question to ask')
    query_parser.add_argument('--tree-dir', help='Tree directory')
    query_parser.add_argument('--method', default='tree_traversal',
                             choices=['tree_traversal', 'collapsed_tree', 'top_k'],
                             help='Retrieval method')
    
    args = parser.parse_args()
    
    if args.command == 'build':
        success = build_tree(
            data_dir=args.data_dir,
            output_dir=args.output_dir,
            use_filtering=not args.no_filtering
        )
        sys.exit(0 if success else 1)
        
    elif args.command == 'stats':
        success = show_stats(tree_dir=args.tree_dir)
        sys.exit(0 if success else 1)
        
    elif args.command == 'query':
        success = query_tree(
            question=args.question,
            tree_dir=args.tree_dir,
            method=args.method
        )
        sys.exit(0 if success else 1)
        
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
