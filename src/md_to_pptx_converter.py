"""
Markdown to PowerPoint Converter
Converts markdown reports to PowerPoint presentations using a template
"""
import re
import os
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor


class MarkdownParser:
    """Parse markdown content into structured sections"""

    def __init__(self, md_content: str):
        self.content = md_content
        self.sections = {}

    def parse(self) -> Dict:
        """Parse markdown into structured data"""
        lines = self.content.split('\n')

        # Extract title and date
        title = lines[0].replace('# ', '').strip() if lines else ""
        date = ""
        for line in lines[:10]:
            if '보고서 날짜' in line or 'Report Date' in line:
                date = line.split('**')[-1].strip() if '**' in line else line.split(':')[-1].strip()
                break

        # Extract sections
        current_section = None
        current_subsection = None
        section_content = []
        section_main_content = []

        for line in lines:
            # Main section (## )
            if line.startswith('## '):
                # Save previous section
                if current_section:
                    if current_subsection:
                        # Save last subsection
                        if current_section not in self.sections:
                            self.sections[current_section] = {'content': '\n'.join(section_main_content), 'subsections': {}}
                        self.sections[current_section]['subsections'][current_subsection] = '\n'.join(section_content)
                    else:
                        # No subsections, just main content
                        self.sections[current_section] = {
                            'content': '\n'.join(section_content),
                            'subsections': {}
                        }

                # Start new section
                current_section = line.replace('## ', '').strip()
                section_content = []
                section_main_content = []
                current_subsection = None

            # Subsection (### )
            elif line.startswith('### '):
                # Save previous subsection if exists
                if current_subsection:
                    if current_section not in self.sections:
                        self.sections[current_section] = {'content': '\n'.join(section_main_content), 'subsections': {}}
                    self.sections[current_section]['subsections'][current_subsection] = '\n'.join(section_content)
                else:
                    # This is the first subsection, save main content
                    section_main_content = section_content[:]

                # Start new subsection
                current_subsection = line.replace('### ', '').strip()
                section_content = []

            else:
                section_content.append(line)

        # Save last section
        if current_section:
            if current_subsection:
                # Save last subsection
                if current_section not in self.sections:
                    self.sections[current_section] = {'content': '\n'.join(section_main_content), 'subsections': {}}
                self.sections[current_section]['subsections'][current_subsection] = '\n'.join(section_content)
            else:
                # No subsections, just main content
                self.sections[current_section] = {
                    'content': '\n'.join(section_content),
                    'subsections': {}
                }

        return {
            'title': title,
            'date': date,
            'sections': self.sections
        }

    @staticmethod
    def extract_tables(content: str) -> List[List[List[str]]]:
        """Extract markdown tables from content"""
        tables = []
        lines = content.split('\n')
        current_table = []
        in_table = False

        for line in lines:
            # Markdown table row
            if '|' in line and line.strip().startswith('|'):
                # Skip separator line
                if re.match(r'^\|[\s\-:|]+\|$', line.strip()):
                    continue

                row = [cell.strip() for cell in line.split('|')[1:-1]]
                current_table.append(row)
                in_table = True
            else:
                if in_table and current_table:
                    tables.append(current_table)
                    current_table = []
                in_table = False

        if current_table:
            tables.append(current_table)

        return tables

    @staticmethod
    def extract_bullet_points(content: str) -> List[str]:
        """Extract bullet points from content"""
        bullets = []
        lines = content.split('\n')

        for line in lines:
            if line.strip().startswith('- '):
                bullets.append(line.strip()[2:])
            elif line.strip().startswith('* '):
                bullets.append(line.strip()[2:])

        return bullets

    @staticmethod
    def extract_chart_references(content: str) -> List[Dict]:
        """Extract chart references from markdown"""
        charts = []
        lines = content.split('\n')

        for i, line in enumerate(lines):
            if '[차트 위치]' in line:
                # Parse chart info
                chart_info = line.replace('[차트 위치]', '').strip()
                chart_data = {
                    'description': chart_info,
                    'type': None,
                    'data_file': None
                }

                # Extract chart type
                if '(LINE)' in chart_info:
                    chart_data['type'] = 'LINE'
                elif '(BAR)' in chart_info:
                    chart_data['type'] = 'BAR'
                elif '(RANGE_BAR)' in chart_info:
                    chart_data['type'] = 'RANGE_BAR'
                elif '(PIE)' in chart_info:
                    chart_data['type'] = 'PIE'

                # Extract data file
                if '데이터:' in chart_info:
                    data_file = chart_info.split('데이터:')[-1].strip()
                    chart_data['data_file'] = data_file

                charts.append(chart_data)

        return charts


class PowerPointConverter:
    """Convert parsed markdown to PowerPoint"""

    def __init__(self, template_path: str):
        self.prs = Presentation(template_path)

    def add_text_to_shape(self, shape, text: str, font_size: int = 12, bold: bool = False):
        """Add text to a shape"""
        if hasattr(shape, 'text_frame'):
            text_frame = shape.text_frame
            text_frame.clear()
            p = text_frame.paragraphs[0]
            run = p.add_run()
            run.text = text
            run.font.size = Pt(font_size)
            run.font.bold = bold
            run.font.name = 'Malgun Gothic'

    def populate_table(self, table_shape, data: List[List[str]]):
        """Populate a table shape with data"""
        if not hasattr(table_shape, 'table'):
            return

        table = table_shape.table

        # Ensure table has enough rows and columns
        rows_needed = len(data)
        cols_needed = len(data[0]) if data else 0

        # Populate cells
        for i, row_data in enumerate(data):
            if i >= len(table.rows):
                break
            for j, cell_data in enumerate(row_data):
                if j >= len(table.columns):
                    break
                cell = table.cell(i, j)
                cell.text = str(cell_data)

                # Format cell text
                for paragraph in cell.text_frame.paragraphs:
                    for run in paragraph.runs:
                        run.font.size = Pt(10)
                        run.font.name = 'Malgun Gothic'

    def add_slide_with_content(self, title: str, content: str, tables: List = None, bullets: List = None):
        """Add a new slide with content"""
        # Use blank layout or title-content layout
        slide_layout = self.prs.slide_layouts[1] if len(self.prs.slide_layouts) > 1 else self.prs.slide_layouts[0]
        slide = self.prs.slides.add_slide(slide_layout)

        # Add title
        if slide.shapes.title:
            slide.shapes.title.text = title

        # Add content to text boxes or create new ones
        # This is a simplified version - you may need to customize based on your template
        return slide

    def save(self, output_path: str):
        """Save the presentation"""
        self.prs.save(output_path)


class MDToPPTXConverter:
    """Main converter class"""

    def __init__(self, template_path: str):
        self.template_path = template_path
        self.parser = None
        self.converter = None

    def convert(self, md_file_path: str, output_path: str = None) -> str:
        """
        Convert markdown file to PowerPoint presentation

        Args:
            md_file_path: Path to markdown file
            output_path: Output path for PPTX file (optional)

        Returns:
            Path to generated PPTX file
        """
        # Read markdown file
        with open(md_file_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        # Parse markdown
        self.parser = MarkdownParser(md_content)
        parsed_data = self.parser.parse()

        # Initialize converter
        self.converter = PowerPointConverter(self.template_path)

        # Populate slides based on parsed data
        self._populate_slides(parsed_data, md_file_path)

        # Generate output path if not provided
        if output_path is None:
            md_path = Path(md_file_path)
            output_path = str(md_path.parent / f"{md_path.stem}.pptx")

        # Save presentation
        self.converter.save(output_path)

        return output_path

    def _populate_slides(self, parsed_data: Dict, md_file_path: str):
        """Populate slides with parsed markdown data"""
        sections = parsed_data['sections']
        title = parsed_data.get('title', '')
        date = parsed_data.get('date', '')

        print(f"[INFO] Populating slides with content from markdown...")
        print(f"[INFO] Title: {title}")
        print(f"[INFO] Found {len(sections)} sections")

        # Populate Slide 1: Executive Summary
        self._populate_slide_1(sections, title, date)

        # Populate Slide 2: Performance Analysis
        self._populate_slide_2(sections)

        # Populate Slide 3: Scenario Analysis
        self._populate_slide_3(sections)

        # Populate Slide 4: Charts
        self._populate_slide_4(sections, md_file_path)

        # Populate Slide 5: Conclusion
        self._populate_slide_5(sections)

    def _populate_slide_1(self, sections: Dict, title: str, date: str):
        """Populate Slide 1 with executive summary"""
        if len(self.converter.prs.slides) < 1:
            return

        slide = self.converter.prs.slides[0]
        print(f"[INFO] Populating Slide 1 (Executive Summary)...")

        # Find summary section
        summary_key = None
        for key in sections.keys():
            if '요약' in key or 'Executive Summary' in key:
                summary_key = key
                break

        if not summary_key:
            print("[WARNING] No summary section found")
            return

        summary_content = sections[summary_key]['content']

        # Extract tables and text
        tables = MarkdownParser.extract_tables(summary_content)
        bullets = MarkdownParser.extract_bullet_points(summary_content)

        # Populate tables
        table_shapes = [s for s in slide.shapes if hasattr(s, 'table')]
        for i, table_data in enumerate(tables):
            if i < len(table_shapes):
                self.converter.populate_table(table_shapes[i], table_data)
                print(f"  - Populated table {i+1} with {len(table_data)} rows")

        # Find text boxes to populate
        text_boxes = [s for s in slide.shapes if hasattr(s, 'text_frame') and
                      s.shape_type in [1, 17]]  # AUTO_SHAPE or TEXT_BOX

        # Get main content paragraphs (non-table, non-bullet)
        lines = [line.strip() for line in summary_content.split('\n')
                 if line.strip() and not line.strip().startswith('|')
                 and not line.strip().startswith('-')
                 and not line.strip().startswith('*')
                 and not line.strip().startswith('#')]

        # Populate text boxes with content
        content_lines = [line for line in lines if len(line) > 20]  # Filter out short lines
        if content_lines and text_boxes:
            for i, text_box in enumerate(text_boxes[:len(content_lines)]):
                if hasattr(text_box, 'text_frame'):
                    text_box.text_frame.clear()
                    p = text_box.text_frame.paragraphs[0]
                    p.text = content_lines[i]
                    p.font.size = Pt(11)
                    p.font.name = 'Malgun Gothic'
                    print(f"  - Populated text box {i+1}")

    def _populate_slide_2(self, sections: Dict):
        """Populate Slide 2 with performance analysis"""
        if len(self.converter.prs.slides) < 2:
            return

        slide = self.converter.prs.slides[1]
        print(f"[INFO] Populating Slide 2 (Performance Analysis)...")

        # Find performance section
        perf_key = None
        for key in sections.keys():
            if '실적 분석' in key or 'Performance' in key:
                perf_key = key
                break

        if not perf_key:
            print("[WARNING] No performance analysis section found")
            return

        performance_section = sections[perf_key]

        # Collect all tables from all subsections
        all_tables = []
        for subsection_name, subsection_content in performance_section.get('subsections', {}).items():
            tables = MarkdownParser.extract_tables(subsection_content)
            all_tables.extend(tables)
            print(f"  - Found {len(tables)} tables in '{subsection_name}'")

        # Populate tables in the slide
        table_shapes = [s for s in slide.shapes if hasattr(s, 'table')]
        for i, table_data in enumerate(all_tables):
            if i < len(table_shapes):
                self.converter.populate_table(table_shapes[i], table_data)
                print(f"  - Populated table {i+1} with {len(table_data)} rows")

    def _populate_slide_3(self, sections: Dict):
        """Populate Slide 3 with scenario analysis"""
        if len(self.converter.prs.slides) < 3:
            return

        slide = self.converter.prs.slides[2]
        print(f"[INFO] Populating Slide 3 (Scenario Analysis)...")

        # Find scenario section
        scenario_key = None
        for key in sections.keys():
            if '시나리오' in key or 'Scenario' in key:
                scenario_key = key
                break

        if not scenario_key:
            print("[WARNING] No scenario analysis section found")
            return

        scenario_section = sections[scenario_key]

        # Collect all tables
        all_tables = []
        for subsection_name, subsection_content in scenario_section.get('subsections', {}).items():
            tables = MarkdownParser.extract_tables(subsection_content)
            all_tables.extend(tables)
            print(f"  - Found {len(tables)} tables in '{subsection_name}'")

        # Populate tables
        table_shapes = [s for s in slide.shapes if hasattr(s, 'table')]
        for i, table_data in enumerate(all_tables):
            if i < len(table_shapes):
                self.converter.populate_table(table_shapes[i], table_data)
                print(f"  - Populated table {i+1} with {len(table_data)} rows")

    def _populate_slide_4(self, sections: Dict, md_file_path: str):
        """Populate Slide 4 with charts"""
        if len(self.converter.prs.slides) < 4:
            return

        slide = self.converter.prs.slides[3]
        print(f"[INFO] Populating Slide 4 (Charts)...")

        # Find chart references
        chart_section = sections.get('추가 차트 분석', {})
        if not chart_section:
            for key in sections.keys():
                if '차트' in key or 'Chart' in key:
                    chart_section = sections[key]
                    break

        if not chart_section:
            print("[WARNING] No chart section found")
            return

        # Extract charts from main content and subsections
        charts = []
        if isinstance(chart_section, dict):
            # Check main content
            content = chart_section.get('content', '')
            charts.extend(MarkdownParser.extract_chart_references(content))

            # Check subsections
            for subsection_name, subsection_content in chart_section.get('subsections', {}).items():
                charts.extend(MarkdownParser.extract_chart_references(subsection_content))
        else:
            charts = MarkdownParser.extract_chart_references(str(chart_section))

        print(f"  - Found {len(charts)} chart references")

        # Try to insert chart images
        md_dir = Path(md_file_path).parent
        picture_shapes = [s for s in slide.shapes if s.shape_type == 13]  # PICTURE type

        for i, chart in enumerate(charts):
            if chart['data_file'] and i < len(picture_shapes):
                # Look for corresponding image file
                chart_name = Path(chart['data_file']).stem.replace('generated_', '')

                # Try different naming patterns
                potential_images = [
                    md_dir / f"generated_{chart_name}.png",
                    md_dir / f"{chart_name}.png",
                    md_dir / chart['data_file'].replace('.csv', '.png')
                ]

                for img_path in potential_images:
                    if img_path.exists():
                        try:
                            # Replace image in picture shape
                            picture = picture_shapes[i]
                            left, top = picture.left, picture.top
                            width, height = picture.width, picture.height

                            # Remove old picture and add new one
                            sp = picture._element
                            sp.getparent().remove(sp)

                            slide.shapes.add_picture(str(img_path), left, top, width, height)
                            print(f"  - Inserted chart image: {img_path.name}")
                            break
                        except Exception as e:
                            print(f"  - Failed to insert image {img_path.name}: {e}")

    def _populate_slide_5(self, sections: Dict):
        """Populate Slide 5 with conclusion"""
        if len(self.converter.prs.slides) < 5:
            return

        slide = self.converter.prs.slides[4]
        print(f"[INFO] Populating Slide 5 (Conclusion)...")

        # Find conclusion section
        conclusion_key = None
        for key in sections.keys():
            if '결론' in key or 'Conclusion' in key or '투자 의견' in key:
                conclusion_key = key
                break

        if not conclusion_key:
            print("[WARNING] No conclusion section found")
            return

        conclusion_content = sections[conclusion_key]['content']

        # Get main paragraphs
        lines = [line.strip() for line in conclusion_content.split('\n')
                 if line.strip() and not line.strip().startswith('|')
                 and not line.strip().startswith('#')
                 and not line.strip().startswith('**투자 의견:**')
                 and len(line.strip()) > 30]

        # Find text boxes
        text_boxes = [s for s in slide.shapes if hasattr(s, 'text_frame') and
                      s.shape_type in [1, 17]]  # AUTO_SHAPE or TEXT_BOX

        # Populate text boxes
        if lines and text_boxes:
            for i, text_box in enumerate(text_boxes[:len(lines)]):
                if hasattr(text_box, 'text_frame'):
                    text_box.text_frame.clear()
                    p = text_box.text_frame.paragraphs[0]
                    p.text = lines[i]
                    p.font.size = Pt(11)
                    p.font.name = 'Malgun Gothic'
                    print(f"  - Populated text box {i+1}")


def main():
    """Main function for command-line usage"""
    import argparse

    parser = argparse.ArgumentParser(description='Convert Markdown report to PowerPoint presentation')
    parser.add_argument('md_file', help='Path to markdown file')
    parser.add_argument('-t', '--template', default='src/data/config/template.pptx',
                        help='Path to PowerPoint template')
    parser.add_argument('-o', '--output', help='Output PPTX file path')

    args = parser.parse_args()

    # Convert
    converter = MDToPPTXConverter(args.template)
    output_path = converter.convert(args.md_file, args.output)

    print(f"[SUCCESS] Conversion completed: {output_path}")


if __name__ == '__main__':
    main()
