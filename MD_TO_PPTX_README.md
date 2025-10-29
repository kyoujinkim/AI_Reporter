# Markdown to PowerPoint Converter

This tool automatically converts markdown reports to PowerPoint presentations using a template.

## Features

- Parses markdown files with structured sections
- Extracts tables, bullet points, and text content
- Maps content to template slides
- Supports chart references and image insertion
- Batch processing capability

## Installation

The converter requires the `python-pptx` library:

```bash
pip install python-pptx
```

## Usage

### Single File Conversion

Convert a single markdown file to PowerPoint:

```bash
python convert_md_to_pptx.py <markdown_file> [output_file]
```

**Example:**
```bash
python convert_md_to_pptx.py src/output/A046890/ai_report_A046890_20251022_105919.md
```

This will create a PowerPoint file in the same directory as the markdown file.

**Specify output location:**
```bash
python convert_md_to_pptx.py src/output/A046890/ai_report_A046890_20251022_105919.md output/my_presentation.pptx
```

### Batch Conversion

Convert all markdown files in a directory:

```bash
python convert_md_to_pptx.py --batch <directory>
```

**Example:**
```bash
python convert_md_to_pptx.py --batch src/output
```

This will process all `.md` files in the directory and subdirectories.

## Template Structure

The converter uses a PowerPoint template located at:
```
src/data/config/template.pptx
```

### Template Slide Mapping

- **Slide 1**: Executive Summary and Key Metrics
- **Slide 2**: Detailed Performance Analysis
- **Slide 3**: Scenario Analysis
- **Slide 4**: Charts and Visual Analysis
- **Slide 5**: Conclusion and Investment Opinion

## Markdown Format Requirements

Your markdown file should follow this structure:

```markdown
# Report Title

**보고서 날짜:** 2025년 9월 25일

---

## 1. 요약 (Executive Summary)

Content here...

---

## 2. 실적 분석 상세

### 2.1. 실적 발표 주요 수치

| Column 1 | Column 2 |
|----------|----------|
| Data 1   | Data 2   |

---

## 3. 다음분기 시나리오(2025년 4분기) 분석

Content here...

---

## 4. 결론 및 투자 의견

Conclusion content...
```

### Supported Elements

1. **Tables**: Standard markdown tables with `|` separators
2. **Bullet Points**: Lines starting with `-` or `*`
3. **Sections**: Headers with `##` (main sections) and `###` (subsections)
4. **Chart References**: Special format for charts:
   ```markdown
   [차트 위치] Chart Description (CHART_TYPE) - 데이터: path/to/data.csv
   ```

## Advanced Usage

### Using a Custom Template

You can specify a custom template:

```python
from src.md_to_pptx_converter import MDToPPTXConverter

converter = MDToPPTXConverter('path/to/your/template.pptx')
output_path = converter.convert('path/to/report.md', 'output.pptx')
```

### Programmatic Usage

```python
from src.md_to_pptx_converter import MDToPPTXConverter

# Create converter with template
converter = MDToPPTXConverter('src/data/config/template.pptx')

# Convert markdown to PowerPoint
output_path = converter.convert(
    md_file_path='src/output/A046890/ai_report_A046890_20251022_105919.md',
    output_path='output/presentation.pptx'
)

print(f"Presentation created: {output_path}")
```

### Parsing Markdown Only

If you just want to parse markdown without converting to PowerPoint:

```python
from src.md_to_pptx_converter import MarkdownParser

with open('report.md', 'r', encoding='utf-8') as f:
    content = f.read()

parser = MarkdownParser(content)
parsed_data = parser.parse()

print(f"Title: {parsed_data['title']}")
print(f"Sections: {list(parsed_data['sections'].keys())}")

# Extract tables
tables = MarkdownParser.extract_tables(content)
print(f"Found {len(tables)} tables")

# Extract bullet points
bullets = MarkdownParser.extract_bullet_points(content)
print(f"Found {len(bullets)} bullet points")
```

## Customization

### Modifying Slide Population Logic

The slide population logic is in the `_populate_slides` method of the `MDToPPTXConverter` class:

```python
# In src/md_to_pptx_converter.py
def _populate_slides(self, parsed_data: Dict, md_file_path: str):
    # Customize how content maps to slides
    sections = parsed_data['sections']

    # Example: Add custom logic for your specific needs
    # ...
```

### Customizing Text Formatting

Modify the `add_text_to_shape` method to change fonts, sizes, and colors:

```python
def add_text_to_shape(self, shape, text: str, font_size: int = 12, bold: bool = False):
    # Customize formatting here
    run.font.size = Pt(font_size)
    run.font.bold = bold
    run.font.name = 'Malgun Gothic'  # Change font
    run.font.color.rgb = RGBColor(0, 0, 0)  # Change color
```

## File Structure

```
AI_Reporter/
├── convert_md_to_pptx.py           # Simple wrapper script
├── src/
│   ├── md_to_pptx_converter.py     # Main converter module
│   ├── examine_pptx_template.py    # Template examination tool
│   └── data/
│       └── config/
│           └── template.pptx       # PowerPoint template
└── output/
    └── A046890/
        ├── ai_report_A046890_20251022_105919.md
        └── test_output.pptx
```

## Troubleshooting

### Common Issues

1. **Module not found error**
   ```
   Solution: pip install python-pptx
   ```

2. **Template not found**
   ```
   Solution: Ensure template.pptx exists at src/data/config/template.pptx
   ```

3. **Encoding errors**
   ```
   Solution: Ensure markdown files are saved with UTF-8 encoding
   ```

4. **Tables not populating correctly**
   ```
   Solution: Check that markdown tables are properly formatted with | separators
   ```

## Examples

### Example 1: Basic Conversion

```bash
python convert_md_to_pptx.py src/output/A046890/ai_report_A046890_20251022_105919.md
```

Output: `src/output/A046890/ai_report_A046890_20251022_105919.pptx`

### Example 2: Batch Processing

```bash
python convert_md_to_pptx.py --batch src/output
```

This will convert all markdown files in the `src/output` directory and its subdirectories.

### Example 3: Integration with Report Generation

```python
# After generating your markdown report
from src.md_to_pptx_converter import MDToPPTXConverter

# Generate markdown report (existing code)
report_path = generate_ai_report(...)  # Your existing function

# Convert to PowerPoint
converter = MDToPPTXConverter('src/data/config/template.pptx')
pptx_path = converter.convert(report_path)

print(f"Report generated: {report_path}")
print(f"PowerPoint created: {pptx_path}")
```

## Notes

- The converter is designed to work with Korean language reports but supports any UTF-8 content
- The template structure should match the expected sections in the markdown
- Chart images should be placed in the same directory as the markdown file
- The converter performs a basic mapping - you may need to customize it for complex layouts

## License

This tool is part of the AI_Reporter project.
