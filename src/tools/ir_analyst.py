import os
from glob import glob

from src.tools import pdf_parser, summarizer
from src.tools.agents import Agent


class IrAnalyst:
    def __init__(self, openai_key):
        print("\n\n🤵IR 발표자료 분석가를 불러옵니다.")
        self.tableagent = Agent(
            api_key=openai_key,
            name="TableAgent",
            description="당신은 표를 분석하는 전문가입니다. 셀 내용을 그대로 재현하지 말고, 주요 결론(지표, 추세, 극값, 변화량, 주목할 만한 비교)을 설명하십시오.",
            model="gpt-4.1-mini"
        )
        self.pdfparser = pdf_parser.PDFParser()
        self.summarizer = summarizer.Summarizer(apikey=openai_key, chunk_tokens=3000, target_summary_tokens=1000)

    def run(self, company_info, out_dir=None):
        code = company_info['stock_code']
        if out_dir is None:
            out_dir = f'./data/A{code}_summary'

        print(f"IR 보고서 분석: {company_info['corp_name']} ({code})")

        # IR 보고서 목록 조회 (최근 5년)
        self.pdfparser.parse_pdf(f'{out_dir}/IR.pdf',
                            out_dir=out_dir,
                            )
        # read md file in markdown folder
        markdown_list = glob(f'{out_dir}/markdown/*.md')
        markdown_content = ""
        for md_file in markdown_list:
            with open(md_file, 'r', encoding='utf-8') as file:
                markdown_content += file.read() + "\n\n"
        summarize = self.summarizer.run_text(markdown_content, 4000)

        # Save IR summary to markdown file
        # create out_dir if not exists
        os.makedirs(out_dir, exist_ok=True)
        with open(f'{out_dir}/ir_summary.md', 'w', encoding='utf-8') as md_file:
            md_file.write(summarize.summary)

        return summarize
