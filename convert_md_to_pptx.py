"""
Simple wrapper script for converting Markdown reports to PowerPoint
Usage: python convert_md_to_pptx.py <markdown_file>
"""
import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from src.md_to_pptx_converter import MDToPPTXConverter


def convert_single_file(md_file: str, template: str = None, output: str = None):
    """Convert a single markdown file to PowerPoint"""

    # Default template path
    if template is None:
        template = Path(__file__).parent / 'src' / 'data' / 'config' / 'template.pptx'
        template = str(template)

    # Check if files exist
    if not os.path.exists(md_file):
        print(f"[ERROR] Markdown file not found: {md_file}")
        return None

    if not os.path.exists(template):
        print(f"[ERROR] Template file not found: {template}")
        return None

    # Convert
    try:
        converter = MDToPPTXConverter(template)
        output_path = converter.convert(md_file, output)
        print(f"[SUCCESS] Converted: {md_file}")
        print(f"[SUCCESS] Output saved to: {output_path}")
        return output_path
    except Exception as e:
        print(f"[ERROR] Conversion failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def convert_batch(directory: str, pattern: str = "*.md", template: str = None):
    """Convert all markdown files in a directory"""

    md_files = list(Path(directory).rglob(pattern))

    if not md_files:
        print(f"[WARNING] No markdown files found in: {directory}")
        return

    print(f"[INFO] Found {len(md_files)} markdown files")

    success_count = 0
    for md_file in md_files:
        print(f"\n[INFO] Processing: {md_file}")
        result = convert_single_file(str(md_file), template)
        if result:
            success_count += 1

    print(f"\n[SUMMARY] Converted {success_count}/{len(md_files)} files successfully")


def main():
    """Main entry point"""

    if len(sys.argv) < 2:
        print("Usage:")
        print("  Single file: python convert_md_to_pptx.py <markdown_file> [output_file]")
        print("  Batch mode:  python convert_md_to_pptx.py --batch <directory>")
        print("\nExamples:")
        print("  python convert_md_to_pptx.py src/output/A046890/ai_report_A046890_20251022_105919.md")
        print("  python convert_md_to_pptx.py --batch src/output")
        sys.exit(1)

    # Batch mode
    if sys.argv[1] == '--batch':
        if len(sys.argv) < 3:
            print("[ERROR] Please specify directory for batch conversion")
            sys.exit(1)
        convert_batch(sys.argv[2])

    # Single file mode
    else:
        md_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else None
        convert_single_file(md_file, output=output_file)


if __name__ == '__main__':
    main()
