"""
Markdown to PowerPoint Converter
Converts markdown reports to PowerPoint presentations using a template
"""
import configparser
import json
import re
import os
from dataclasses import dataclass
from pydantic import BaseModel
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from pptx import Presentation
from pptx.enum.dml import MSO_FILL
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.enum.dml import MSO_COLOR_TYPE
from pptx.util import Inches, Cm, Pt
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor

from src.tools.agents import Agent

class ReportManager:
    class keyword_table(BaseModel):
        keynumber1: str
        keyword1: str
        detail1: str
        keynumber2: str
        keyword2: str
        detail2: str
        keynumber3: str
        keyword3: str
        detail3: str

    class text_box(BaseModel):
        content: str

    def __init__(self, openai_key):
        print("\n\n🤵리포트 내용을 포맷화하는 Product Manager를 불러옵니다.")
        self.PMagent = Agent(
            api_key=openai_key,
            name="Format Product manager",
            description="당신은 md 포맷의 리포트를 원하는 형식으로 전환하는 Product Manager입니다. 형식에 맞게 Contents 구성을 바꿔주세요.",
            model="gpt-4.1-mini"
        )

    def run(self, content, format, additional_prompt=""):
        prompt = f""" 입력된 Content의 내용을 형식에 맞게 구성을 바꿔주세요.
        {additional_prompt}

        # Content
        - {content}
        """

        return self.PMagent.run_with_structured_format(prompt, format)

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


class ThemeColor:
    """Convert parsed markdown to PowerPoint"""
    darkblue = RGBColor(0x06, 0x43, 0x67)
    blue = RGBColor(0x00, 0x5B, 0x8E)
    lightblue = RGBColor(0x69, 0x98, 0xBD)
    red = RGBColor(0xFF, 0x00, 0x00)


class ThemeMargin:
    """Set Theme Margin left, right, top, bottom"""
    standard = (0.2, 0.2, 0.15, 0.15)
    wide = (0.2, 0.2, 0.2, 0.2)
    narrow = (0.1, 0.1, 0, 0)


class MDToPPTXConverter:
    """Main converter class"""

    def __init__(self, template_path: str, shape_path: str, config_path: str = "D:/config.ini"):
        self.template_prs = self._load(template_path)
        self.shape_prs = self._load(shape_path)
        self.parser = None
        self.converter = None
        self.themecolor = ThemeColor()
        self.thememargin = ThemeMargin()

        # load API key and AI agent
        self.config_path = config_path
        self._load_config()
        self.pm = ReportManager(openai_key=self.api_key)

    def _load_config(self):
        """설정 파일에서 API 키 로드"""
        config = configparser.ConfigParser()
        config.read(self.config_path, encoding='utf-8')
        self.api_key = config.get("openai", "API_KEY")

    @staticmethod
    def _load(template_path: str):
        return Presentation(template_path)

    @staticmethod
    def _save(prs, output_path: str):
        """Save the presentation"""
        prs.save(output_path)

    @staticmethod
    def _add_text_to_shape(shape, text: str, font: str = 'Malgun Gothic', font_size: int = 12, bold: bool = False):
        """Add text to a shape"""
        if hasattr(shape, 'text_frame'):
            text_frame = shape.text_frame
            text_frame.clear()
            p = text_frame.paragraphs[0]
            run = p.add_run()
            run.text = text
            run.font.size = Pt(font_size)
            run.font.bold = bold
            run.font.name = font

    @staticmethod
    def _populate_table(table_shape, data: List[List[str]]):
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

        # Populate slides based on parsed data
        self._populate_slides(parsed_data, md_file_path)

        # Generate output path if not provided
        if output_path is None:
            md_path = Path(md_file_path)
            output_path = str(md_path.parent / f"{md_path.stem}.pptx")

        # Save presentation
        self._save(self.template_prs, output_path)

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

    def _split_md(self, content: str) -> str:
        """Split markdown by text and table syntax from contet"""
        lines = content.split('\n')

        split_lines = []
        tmp_content = ''
        in_table = False
        for line in lines:
            if '|' in line and line.strip().startswith('|') and in_table is False:
                if tmp_content:
                    split_lines.append({'text':tmp_content})
                in_table = True
                tmp_content = line
            elif not ('|' in line) and not line.strip().startswith('|') and in_table is True:
                if tmp_content:
                    tmp_content = MarkdownParser.extract_tables(tmp_content)
                    split_lines.append({'table': tmp_content})
                in_table = False
                tmp_content = line
            else:
                if tmp_content:
                    tmp_content = tmp_content + '\n' + line
                else:
                    tmp_content = line

        if in_table:
            split_lines.append({'table':tmp_content})
        else:
            split_lines.append({'text':tmp_content})

        return split_lines

    @staticmethod
    def _find_shape_by_name(slide, name: str):
        """Find shape by name in a slide"""
        for shape in slide.shapes:
            if shape.name == name:
                return shape
        return None

    @staticmethod
    def _check_color_type(color_obj):
        if color_obj.type == MSO_COLOR_TYPE.RGB:
            # 1. 타입이 RGB인 경우 (예: "FF0000")
            # 이 경우에만 .rgb 속성이 존재합니다.
            type = 'rgb'
            color_info = color_obj.rgb

        elif color_obj.type == MSO_COLOR_TYPE.SCHEME:
            # 2. 타입이 SCHEME인 경우 (지금 겪으신 문제)
            # .rgb 대신 .theme_color 속성을 사용합니다.
            type = 'scheme'
            color_info = color_obj.theme_color

        else:
            # 3. (기타) 타입이 AUTO(자동)인 경우
            type = 'auto'
            color_info = None

        return type, color_info

    @staticmethod
    def _convert_shape_text(shape, text: str, is_cell:bool=False) -> bool:
        """Convert cell text with formatting"""
        # 1. Get the TextFrame
        tf = shape.text_frame

        # 2. Ensure there is at least one paragraph
        if not tf.paragraphs:
            tf.add_paragraph()

        # 3. Get the first paragraph
        p = shape.text_frame.paragraphs[0]

        # 4. Ensure there is at least one run
        if not p.runs:
            p.add_run()

        # 5. Set the text of the first run
        p.runs[0].text = text

        # 7. (CRITICAL) Delete all other runs (from index 1 onwards)
        # This removes any leftover text from the original content

        # We must loop from the last run (index len-1) down to the second run (index 1)
        for i in range(len(p.runs) - 1, 0, -1):
            r = p.runs[i]
            # This is the "secret" way to remove a run.
            # It uses the internal lxml element representation.
            p._p.remove(r._r)

        # --- Cleanup Step 2: Delete all other paragraphs from the text_frame ---
        # Loop backwards from the last paragraph down to the second paragraph (index 1)
        for i in range(len(tf.paragraphs) - 1, 0, -1):
            p_to_remove = tf.paragraphs[i]
            tf._txBody.remove(p_to_remove._p)  # Remove the paragraph element

        '''font = shape.text_frame.paragraphs[0].runs[0].font
        font_name = font.name
        font_size = font.size
        font_bold = font.bold
        font_type, font_color = MDToPPTXConverter._check_color_type(font.color)
        if is_cell:
            font_margin = (shape.margin_left, shape.margin_right, shape.margin_top, shape.margin_bottom)
        font_align = shape.text_frame.paragraphs[0].alignment

        # assign new value
        shape.text = text

        # clear cell and re-apply font settings
        font = shape.text_frame.paragraphs[0].font
        shape.text_frame.paragraphs[0].alignment = font_align
        font.name = font_name
        font.size = font_size
        font.bold = font_bold
        if font_type == 'rgb':
            font.color.rgb = font_color
        elif font_type == 'scheme':
            font.color.theme_color = font_color
        else:
            pass
        if is_cell:
            shape.margin_left = font_margin[0]
            shape.margin_right = font_margin[1]
            shape.margin_top = font_margin[2]
            shape.margin_bottom = font_margin[3]'''

        return True

    def _populate_slide_1(self, sections: Dict, title: str, date: str):
        """Populate Slide 1 with executive summary"""
        if len(self.template_prs.slides) < 1:
            return

        slide = self.template_prs.slides[0]
        print(f"[INFO] Populating Slide 1 (Executive Summary)...")

        summary_key = list(sections.keys())[0]
        # Find summary sections
        summary_content = sections[summary_key]['content']
        summary_subsections = sections[summary_key].get('subsections', {})

        # subsections contains two sections. Summary and Keywords
        subsection_key = list(summary_subsections.keys())
        subsection_content = self._split_md(summary_subsections[subsection_key[0]])
        subsection_keyword = self._split_md(summary_subsections[subsection_key[1]])

        subsection_keyword_formatted = self.pm.run(subsection_keyword, self.pm.keyword_table)
        keyword_shape = self._find_shape_by_name(slide, 'keywords')

        # change text inside keyword_shapes' table to subsection_keyword_formatted
        if keyword_shape and hasattr(keyword_shape, 'table'):
            table = keyword_shape.table
            for i in range(3):
                key_num = getattr(subsection_keyword_formatted, f'keynumber{i+1}', '')
                keyword = getattr(subsection_keyword_formatted, f'keyword{i+1}', '')
                detail = getattr(subsection_keyword_formatted, f'detail{i+1}', '')

                if i < len(table.columns):
                    if key_num:
                        self._convert_shape_text(table.cell(0, i), key_num, True)
                    if keyword:
                        self._convert_shape_text(table.cell(1, i), keyword, True)
                    if detail:
                        self._convert_shape_text(table.cell(2, i), detail, True)

        if len(subsection_content)>1:
            subsection_content_formatted = self.pm.run(subsection_content, self.pm.text_box, "").content
        else:
            subsection_content_formatted = subsection_content[0]['text']
        summary_shape = self._find_shape_by_name(slide, 'summary')
        self._convert_shape_text(summary_shape, subsection_content_formatted)

        a = 1

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
    converter = MDToPPTXConverter('data/config/template.pptx', 'data/config/template_shapes.pptx')
    a = converter.convert('output/A095340/ai_report_A095340_20251030_165119.md'
                          , 'output/A095340/test_report.pptx')
    print(f"[SUCCESS] Conversion completed: {a}")
