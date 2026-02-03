"""
Markdown to PowerPoint Converter
Converts markdown reports to PowerPoint presentations using a template
"""
import configparser
import re
import datetime as dt

from pydantic import BaseModel
from pathlib import Path
from typing import List, Dict
from pptx import Presentation
from pptx.enum.dml import MSO_COLOR_TYPE
from pptx.util import Pt
from pptx.dml.color import RGBColor

from src.tools.agents import Agent

class InvestorImplication(BaseModel):
    """
    Investor Implication Structure
    'implication' field는 주요 implication을 3~5개 이내 단어로 제시하세요.
    'implication_detail' field는 각 implication에 대한 주요 detail을 정리하세요. 한 문장의 짧은 명사형 문장으로 작성해야합니다(ex. ... 목표로 제시, ... 단기 수익성에 부담, ... 관리 필요).
    """
    implication1: str
    implication1_detail: str
    implication2: str
    implication2_detail: str
    implication3: str
    implication3_detail: str
    implication4: str
    implication4_detail: str

class KeywordTable(BaseModel):
    keynumber1: str
    keyword1: str
    detail1: str
    keynumber2: str
    keyword2: str
    detail2: str
    keynumber3: str
    keyword3: str
    detail3: str

class EarningData(BaseModel):
    '''
    Earning Data Structure
    actual: 실제 발표된 실적 수치
    consensus: 컨센서스 수치
    difference: 실제 실적과 컨센서스의 차이(%)
    '''
    actual: float
    consensus: float
    difference: float

class CurrQEarning(BaseModel):
    sales: EarningData
    operating_profit: EarningData
    shareholders_net_profit: EarningData

class EarningEstimationRange(BaseModel):
    """
    Earning Estimation Range Structure
    시나리오별 매출, 영업이익, 순이익 수치 범위를 간략히 제시하세요.
    '최저금액 ~ 최고금액'으로 작성하세요.
    """
    sales_range: str
    operating_profit_range: str
    net_profit_range: str

class EarningPoint(BaseModel):
    point1: str
    point_detail_bulletin1: str
    point2: str
    point_detail_bulletin2: str
    point3: str
    point_detail_bulletin3: str

class ScenarioAnalysis(BaseModel):
    """
    Scenario Analysis Structure
    시나리오별 매출, 영업이익, 순이익 전망을 간략히 서술하세요.
    매출, 영업이익, 순이익이 측정된 이유를 명사형(~예상. ~전망. ~예측)으로 간략히 작성하세요.
    단, 매출, 영업이익, 순이익 수치 범위는 이미 제시된 내용이므로 포함하지 마세요.
    """
    sales_scenario: str
    operating_profit_scenario: str
    net_profit_scenario: str

class TextBox(BaseModel):
    content: str

class ReportManager:
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

    def __init__(self, template_path: str, config_path: str = "D:/config.ini"):
        self.template_prs = self._load(template_path)
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

        # md_file_path contains info about company f"aireport_{self.fncode}_{self.name}_{self.market}_{timestamp}.md"
        _, code, name, market, date, hour = md_file_path.split('\\')[-1].replace('.md','').split('_')
        code = code.replace('A', '')
        code = f'({code}.{market})'
        date = dt.datetime.strptime(date, '%Y%m%d').strftime('%Y/%m/%d')
        date_text = f"Company Report : {date}"

        # Parse markdown
        self.parser = MarkdownParser(md_content)
        parsed_data = self.parser.parse()

        # Set code, name, and date in all slides
        self._set_code_name_date(code, name, date_text)

        # Populate slides based on parsed data
        self._populate_slides(parsed_data)

        # Generate output path if not provided
        if output_path is None:
            md_path = Path(md_file_path)
            output_path = str(md_path.parent / f"{md_path.stem}.pptx")

        # Save presentation
        self._save(self.template_prs, output_path)

        return output_path

    def _populate_slides(self, parsed_data: Dict):
        """Populate slides with parsed markdown data"""
        sections = parsed_data['sections']
        title = parsed_data.get('title', '')

        print(f"[INFO] Populating slides with content from markdown...")
        print(f"[INFO] Title: {title}")
        print(f"[INFO] Found {len(sections)} sections")

        # Populate Slide 1: Executive Summary
        self._populate_slide_1(sections)

        # Populate Slide 2: Performance Analysis
        self._populate_slide_2(sections)

        # Populate Slide 3: Scenario Analysis
        self._populate_slide_3(sections)

        # Populate Slide 4: Conclusion
        self._populate_slide_4(sections)

        return True

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

        # We must loop from the last run (index len-1) down to the second run (index 1)
        for i in range(len(p.runs) - 1, 0, -1):
            r = p.runs[i]
            p._p.remove(r._r)

        # --- Cleanup Step 2: Delete all other paragraphs from the text_frame ---
        # Loop backwards from the last paragraph down to the second paragraph (index 1)
        for i in range(len(tf.paragraphs) - 1, 0, -1):
            p_to_remove = tf.paragraphs[i]
            tf._txBody.remove(p_to_remove._p)  # Remove the paragraph element

        return True

    def _set_code_name_date(self, code: str, name: str, date: str):
        """Set code, name, and date in the slide"""
        for slide in self.template_prs.slides:
            code_shape = self._find_shape_by_name(slide, 'company_code')
            name_shape = self._find_shape_by_name(slide, 'company_name')
            date_shape = self._find_shape_by_name(slide, 'date')

            if code_shape:
                self._convert_shape_text(code_shape, code)
            if name_shape:
                self._convert_shape_text(name_shape, name)
            if date_shape:
                self._convert_shape_text(date_shape, date)

        return True

    def _populate_slide_1(self, sections: Dict):
        """Populate Slide 1 with executive summary"""
        if len(self.template_prs.slides) < 1:
            return

        slide = self.template_prs.slides[0]
        print(f"[INFO] Populating Slide 1 (Executive Summary and Earning Review Part1)...")

        summary_key = list(sections.keys())[0]

        # subsections contains two sections. Summary and Keywords
        summary_subsections = sections[summary_key].get('subsections', {})
        subsection_key = list(summary_subsections.keys())

        # Find summary sections
        summary_content = sections[summary_key]['content']
        for key in subsection_key:
            if '요약' in key or 'Summary' in key:
                summary_content += summary_subsections[key]
        summary_shape = self._find_shape_by_name(slide, 'summary')
        self._convert_shape_text(summary_shape, summary_content)

        subsection_keyword = self._split_md(summary_subsections[subsection_key[-1]])
        subsection_keyword_formatted = self.pm.run(subsection_keyword, KeywordTable)
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

        # Extract Section 2
        sec2_key = list(sections.keys())[1]
        sec2_subsection = sections[sec2_key]['subsections']
        sec2_subsection_key = list(sec2_subsection.keys())

        # Extract Section 2-1
        sec2_1 = sec2_subsection[sec2_subsection_key[0]]
        sec2_1_formatted = self.pm.run(sec2_1, CurrQEarning)
        earning_table_shape = self._find_shape_by_name(slide, 'earning_table')

        # change text inside earning_table_shape's table to sec2_1_formatted
        if earning_table_shape and hasattr(earning_table_shape, 'table'):
            table = earning_table_shape.table
            for i, n in zip([1, 2, 3], ['sales', 'operating_profit', 'shareholders_net_profit']):
                actual = getattr(sec2_1_formatted, n, '').actual
                consensus = getattr(sec2_1_formatted, n, '').consensus
                if consensus == '' or consensus == 0:
                    difference = 'N/A'
                elif 0 > actual > consensus:
                    difference = f'적자축소({actual - consensus:,.0f})'
                elif 0 > consensus > actual:
                    difference = f'적자확대({actual - consensus:,.0f})'
                elif consensus >= 0 > actual:
                    difference = f'적자전환({actual - consensus:,.0f})'
                elif actual >= 0 > consensus:
                    difference = f'흑자전환({actual - consensus:,.0f})'
                else:
                    difference = f'{(actual / consensus - 1)*100:,.1f}'

                if i < len(table.columns):
                    self._convert_shape_text(table.cell(i, 1), f'{actual:,.0f}', True)
                    self._convert_shape_text(table.cell(i, 2), f'{consensus:,.0f}', True)
                    self._convert_shape_text(table.cell(i, 3), difference, True)

        # Extract Section 2-2
        sec2_2 = sec2_subsection[sec2_subsection_key[1]]
        sec2_2_formatted = self.pm.run(sec2_2, EarningPoint)
        for i in range(1, 4):
            topic = getattr(sec2_2_formatted, f'point{i}', '')
            detail = getattr(sec2_2_formatted, f'point_detail_bulletin{i}', '')

            topic_shape = self._find_shape_by_name(slide, f'earning_topic{i}')
            detail_shape = self._find_shape_by_name(slide, f'earning_topic{i}_detail')

            if topic_shape:
                self._convert_shape_text(topic_shape, topic)
            if detail_shape:
                self._convert_shape_text(detail_shape, detail)

        return True

    def _populate_slide_2(self, sections: Dict):
        """Populate Slide 2 with performance analysis"""
        if len(self.template_prs.slides) < 2:
            return

        slide = self.template_prs.slides[1]
        print(f"[INFO] Populating Slide 2 (Earning Review Part 2)...")

        sec2 = list(sections.keys())[1]
        sec2_sub = sections[sec2]['subsections']
        sec2_subkey = list(sec2_sub.keys())

        # Find 2.3 content
        content = sec2_sub[sec2_subkey[2]]
        shape = self._find_shape_by_name(slide, 'extraordinary')
        table = shape.table
        self._convert_shape_text(table.cell(1, 0), content, True)

        # Find 2.4 content
        content = sec2_sub[sec2_subkey[3]]
        shape = self._find_shape_by_name(slide, 'comment')
        table = shape.table
        self._convert_shape_text(table.cell(1, 0), content, True)

        # Find 2.5 content
        content = sec2_sub[sec2_subkey[4]]
        content_formatted = self.pm.run(content, InvestorImplication)
        shape = self._find_shape_by_name(slide, 'investor_view')
        table = shape.table
        for i in [0, 1]:
            implication1 = getattr(content_formatted, f'implication{i*2+1}', '')
            detail1 = getattr(content_formatted, f'implication{i*2+1}_detail', '')
            implication2 = getattr(content_formatted, f'implication{i*2+2}', '')
            detail2 = getattr(content_formatted, f'implication{i*2+2}_detail', '')

            self._convert_shape_text(table.cell(i*2+1, 0), implication1, True)
            self._convert_shape_text(table.cell(i*2+2, 0), detail1, True)
            self._convert_shape_text(table.cell(i*2+1, 2), implication2, True)
            self._convert_shape_text(table.cell(i*2+2, 2), detail2, True)

        return True

    def _populate_slide_3(self, sections: Dict):
        """Populate Slide 3 with scenario analysis"""
        if len(self.template_prs.slides) < 3:
            return

        slide = self.template_prs.slides[2]
        print(f"[INFO] Populating Slide 3 (Scenario Analysis)...")

        # split subsection
        sec3 = list(sections.keys())[2]
        sec3_sub = sections[sec3]['subsections']
        sec3_subkey = list(sec3_sub.keys())

        earning_range_section = ""
        scenario_section = ""
        implication_section = ""
        for key in sec3_subkey:
            if "범위" in key:
                earning_range_section = sec3_sub[key]
            elif "시나리오" in key:
                scenario_section = sec3_sub[key]
            elif "시사점" in key:
                implication_section = sec3_sub[key]

        # set earning range into table
        content_formatted_range = self.pm.run(earning_range_section, EarningEstimationRange)
        shape = self._find_shape_by_name(slide, 'next_quarter')
        table = shape.table
        for i, n in zip([1, 2, 3], ['sales_range', 'operating_profit_range', 'net_profit_range']):
            range_text = getattr(content_formatted_range, n, '')
            self._convert_shape_text(table.cell(2, i), range_text, True)

        # set scenario analysis into text boxes
        content_formatted_scenario = self.pm.run(scenario_section, ScenarioAnalysis)
        shape = self._find_shape_by_name(slide, 'scenario_reason')
        table = shape.table
        for i, n, n2, k in zip([0, 2, 4]
                , ['sales_scenario', 'operating_profit_scenario', 'net_profit_scenario']
                , ['sales_range', 'operating_profit_range', 'net_profit_range']
                , ['매출액', '영업이익' ,'지배순이익']):
            scenario_text = getattr(content_formatted_scenario, n, '')
            range_text = getattr(content_formatted_range, n2, '')
            self._convert_shape_text(table.cell(1, i), f'{k} ({range_text} 억원)', True)
            self._convert_shape_text(table.cell(2, i), scenario_text, True)

        # set implication into text boxes
        content_formatted_implication = self.pm.run(implication_section, InvestorImplication)
        shape = self._find_shape_by_name(slide, 'investor_view')
        table = shape.table
        for i in [0, 1]:
            implication1 = getattr(content_formatted_implication, f'implication{i*2+1}', '')
            detail1 = getattr(content_formatted_implication, f'implication{i*2+1}_detail', '')
            implication2 = getattr(content_formatted_implication, f'implication{i*2+2}', '')
            detail2 = getattr(content_formatted_implication, f'implication{i*2+2}_detail', '')

            self._convert_shape_text(table.cell(i*2+1, 0), implication1, True)
            self._convert_shape_text(table.cell(i*2+2, 0), detail1, True)
            self._convert_shape_text(table.cell(i*2+1, 2), implication2, True)
            self._convert_shape_text(table.cell(i*2+2, 2), detail2, True)

        return True

    def _populate_slide_4(self, sections: Dict):
        """Populate Slide 4 with charts"""
        if len(self.template_prs.slides) < 4:
            return

        slide = self.template_prs.slides[3]
        print(f"[INFO] Populating Slide 4 (Charts)...")

        # split subsection
        sec4 = list(sections.keys())[3]
        sec4_sub = sections[sec4]['subsections']
        sec4_subkey = list(sec4_sub.keys())

        conclusion = ""
        investment_point = ""
        caution_point = ""
        final_evaluation = ""
        for key in sec4_subkey:
            if "결론" in key:
                conclusion = sec4_sub[key]
            elif "투자포인트" in key:
                investment_point = sec4_sub[key]
            elif "주의포인트" in key:
                caution_point = sec4_sub[key]
            elif "평가" in key:
                final_evaluation = sec4_sub[key]

        # split conclusion into 2 parts by paragraph
        conclusion_text = conclusion.split('\n\n')
        if len(conclusion_text) >= 2:
            conclusion_part1 = conclusion_text[0]
            conclusion_part2 = '\n\n'.join(conclusion_text[1:])
        else:
            conclusion_part1 = conclusion
            conclusion_part2 = ""

        # set conclusion into text boxes
        shape = self._find_shape_by_name(slide, 'conclusion_text')
        self._convert_shape_text(shape, conclusion_part1)
        shape = self._find_shape_by_name(slide, 'conclusion_text2')
        self._convert_shape_text(shape, conclusion_part2)

        # set investment point into table
        shape = self._find_shape_by_name(slide, 'point1')
        table = shape.table
        self._convert_shape_text(table.cell(1, 0), investment_point, True)

        # set caution point into table
        shape = self._find_shape_by_name(slide, 'point2')
        table = shape.table
        self._convert_shape_text(table.cell(1, 0), caution_point, True)

        # set final evaluation into textbox
        shape = self._find_shape_by_name(slide, 'final_comment')
        self._convert_shape_text(shape, final_evaluation)

        return True


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
    a = converter.convert(r'C:\Users\NHWM\PycharmProjects\AI_Reporter\output\A353200\ai_report_A353200_20260129_170552.md'
                          , 'tmp.pptx')
    print(f"[SUCCESS] Conversion completed: {a}")
