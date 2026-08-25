
"""Filtered document parser for extracting sections from financial reports."""
import re
import json
from typing import Dict, List, Optional, Any
from pathlib import Path


class FilteredDocumentParser:
    """Parser for extracting sections from financial documents."""
    
    def __init__(self, sections_to_extract: Optional[List[str]] = None):
        """
        Initialize the filtered document parser.
        
        Args:
            sections_to_extract: List of section names to extract. If None, uses all default sections.
        """
        self.default_sections = [
            "board_of_directors_changes",
            "projects_and_initiatives",
            "ai_and_digital_initiatives",
            "government_programs",
            "investments_and_capex",
            "corporate_actions",
            "employee_information",
            "operational_metrics",
            "corporate_governance"
        ]
        
        self.sections_to_extract = sections_to_extract or self.default_sections
        
        # Define section patterns for regex matching (based on working code)
        self.section_patterns = {
            "board_of_directors_changes": r"\*?\*?Board of Directors Changes?\*?\*?",
            "projects_and_initiatives": r"\*?\*?Projects and Major Initiatives?\*?\*?",
            "ai_and_digital_initiatives": r"\*?\*?AI and Digital Initiatives?\*?\*?",
            "government_programs": r"\*?\*?Government Programs?\*?\*?",
            "investments_and_capex": r"\*?\*?Investments and Capital Expenditure?\*?\*?",
            "corporate_actions": r"\*?\*?Corporate Actions?\*?\*?",
            "employee_information": r"\*?\*?Employee Information\*?\*?",
            "operational_metrics": r"\*?\*?Operational Metrics?\*?\*?",
            "corporate_governance": r"\*?\*?Corporate Governance\*?\*?"
        }
    
    def generate_system_prompt(self) -> str:
        """Generate system prompt for LlamaParse."""
        prompt = '''You are a document extraction agent.
            Extract the following information from THIS PAGE ONLY:
            1. Board of Directors Changes
            2. Projects and Major Initiatives
            3. AI and Digital Initiatives
            4. Government Programs
            5. Investments and Capital Expenditure
            6. Corporate Actions
            7. Employee Information
            8. Operational Metrics
            9. Corporate Governance

            IMPORTANT: For each section, if no information is found on this page, write exactly: "Not found in the page"
            If information exists, extract exact details concisely.'''
        
        return prompt
    
    def consolidate_sections(self, raw_text: str) -> Dict[str, List[str]]:
        """Consolidate extracted sections from page-wise results."""
        # Initialize consolidated data structure
        consolidated = {section: [] for section in self.sections_to_extract}
        
        # Split text into chunks (assuming each page/section starts with "1.")
        chunks = re.split(r'(?=\d+\.\s+\*?\*?Board)', raw_text)
        
        for chunk in chunks:
            if not chunk.strip():
                continue
                
            for key, pattern in self.section_patterns.items():
                if key not in self.sections_to_extract:
                    continue
                    
                # Find the section in the chunk
                match = re.search(pattern, chunk, re.IGNORECASE)
                if match:
                    # Extract content after the section header until the next section
                    start = match.end()
                    # Find the next section or end of chunk
                    next_section = re.search(r'\n\d+\.\s+\*?\*?[A-Z]|\n\*?\*?[A-Z][a-z]+', chunk[start:])
                    if next_section:
                        content = chunk[start:start + next_section.start()].strip()
                    else:
                        content = chunk[start:].strip()
                    
                    # Process bullet points
                    if content:
                        lines = content.split('\n')
                        for line in lines:
                            line = line.strip()
                            # Skip "Not found in the page" and similar statements
                            if line and not re.search(r'not found in the page|no (specific )?information|not found|no mention', line, re.IGNORECASE):
                                # Remove leading bullet points and dashes
                                line = re.sub(r'^[-•*]\s*', '', line)
                                if line and line not in consolidated[key]:
                                    consolidated[key].append(line)
        
        # Remove empty sections and duplicates
        final_output = {}
        for key, values in consolidated.items():
            if values:
                # Remove duplicates while preserving order
                unique_values = []
                seen = set()
                for v in values:
                    if v.lower() not in seen:
                        seen.add(v.lower())
                        unique_values.append(v)
                final_output[key] = unique_values
        
        return final_output
    
    def convert_to_text(self, consolidated_data: Dict[str, List[str]]) -> str:
        """
        Convert consolidated data to plain text format for embedding.
        
        Args:
            consolidated_data: Dictionary of section name to content list
        
        Returns:
            Plain text string
        """
        text_parts = []
        
        for section, items in consolidated_data.items():
            if not items:
                continue
            
            # Format section name
            section_title = section.replace("_", " ").title()
            text_parts.append(f"\n{section_title}:")
            
            # Add items
            for item in items:
                text_parts.append(f"  - {item}")
        
        return "\n".join(text_parts)
    
    def convert_to_markdown(self, consolidated_data: Dict[str, List[str]]) -> str:
        """
        Convert consolidated data to markdown format.
        
        Args:
            consolidated_data: Dictionary of section name to content list
        
        Returns:
            Markdown string
        """
        md_parts = []
        
        for section, items in consolidated_data.items():
            if not items:
                continue
            
            # Format section name
            section_title = section.replace("_", " ").title()
            md_parts.append(f"\n## {section_title}\n")
            
            # Add items
            for item in items:
                md_parts.append(f"- {item}")
        
        return "\n".join(md_parts)
    
    def convert_to_json(self, consolidated_data: Dict[str, List[str]]) -> str:
        """
        Convert consolidated data to JSON format.
        
        Args:
            consolidated_data: Dictionary of section name to content list
        
        Returns:
            JSON string
        """
        return json.dumps(consolidated_data, indent=2)
    
    def save_outputs(
        self, 
        consolidated_data: Dict[str, List[str]], 
        output_dir: str,
        base_filename: str = "filtered_output"
    ) -> Dict[str, str]:
        """
        Save consolidated data in multiple formats.
        
        Args:
            consolidated_data: Dictionary of section name to content list
            output_dir: Directory to save files
            base_filename: Base name for output files
        
        Returns:
            Dictionary mapping format to file path
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        saved_files = {}
        
        # Save as JSON
        json_path = output_path / f"{base_filename}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(self.convert_to_json(consolidated_data))
        saved_files["json"] = str(json_path)
        
        # Save as Markdown
        md_path = output_path / f"{base_filename}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(self.convert_to_markdown(consolidated_data))
        saved_files["markdown"] = str(md_path)
        
        # Save as plain text
        txt_path = output_path / f"{base_filename}.txt"
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(self.convert_to_text(consolidated_data))
        saved_files["text"] = str(txt_path)
        
        return saved_files
    
    def get_statistics(self, consolidated_data: Dict[str, List[str]]) -> Dict[str, Any]:
        """
        Get statistics about the consolidated data.
        
        Args:
            consolidated_data: Dictionary of section name to content list
        
        Returns:
            Dictionary with statistics
        """
        total_items = sum(len(items) for items in consolidated_data.values())
        sections_with_data = sum(1 for items in consolidated_data.values() if items)
        
        return {
            "total_sections": len(self.sections_to_extract),
            "sections_with_data": sections_with_data,
            "total_items": total_items,
            "coverage": (sections_with_data / len(self.sections_to_extract)) * 100 if self.sections_to_extract else 0,
            "items_per_section": {
                section: len(items) 
                for section, items in consolidated_data.items() 
                if items
            }
        }
