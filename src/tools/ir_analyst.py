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
        self.script_analysis_agent = Agent(
            api_key=openai_key,
            name="ScriptAnalysisAgent",
            description=f"""
            당신은 IR 프레젠테이션 자료 요약본과 IR 발표 스크립트 요약본을 통합적으로 분석하는 AI 에이전트입니다.
            """,
            model="gpt-4.1-mini"
        )
        self.pdfparser = pdf_parser.PDFParser()
        self.summarizer = summarizer.Summarizer(apikey=openai_key, chunk_tokens=3000, target_summary_tokens=1000)

    def run(self, company_info, out_dir=None):
        code = company_info['stock_code']
        if out_dir is None:
            out_dir = f'./data/A{code}_summary'

        print(f"IR 보고서 분석: {company_info['corp_name']} ({code})")

        # IR Report와 Script 파일이 각각 존재하는지 확인
        if os.path.exists(f'{out_dir}/IR.pdf'):
            print(f"IR.pdf 파일이 존재합니다. IR 프레젠테이션 자료를 분석합니다.")
            self.pdfparser.parse_pdf(f'{out_dir}/IR.pdf',
                                     out_dir=out_dir+'/ir',
                                     )
            # read md file in markdown folder
            markdown_list = glob(f'{out_dir}/ir/markdown/*.md')
            markdown_content = ""
            for md_file in markdown_list:
                with open(md_file, 'r', encoding='utf-8') as file:
                    markdown_content += file.read() + "\n\n"
            IR_summarize = self.summarizer.run_text(markdown_content, 4000)
            ir_exist = True
        else:
            ir_exist = False

        if os.path.exists(f'{out_dir}/SCRIPT.pdf'):
            print(f"SCRIPT.pdf 파일이 존재합니다. IR 발표 스크립트 자료를 분석합니다.")
            self.pdfparser.parse_pdf(f'{out_dir}/SCRIPT.pdf',
                                     out_dir=out_dir+'/script',
                                     )
            # read md file in markdown folder
            markdown_list = glob(f'{out_dir}/script/markdown/*.md')
            markdown_content = ""
            for md_file in markdown_list:
                with open(md_file, 'r', encoding='utf-8') as file:
                    markdown_content += file.read() + "\n\n"
            SCRIPT_summarize = self.summarizer.run_text(markdown_content, 4000)
            script_exist = True
        else:
            script_exist = False

        if ir_exist and script_exist:
            # Combine IR and SCRIPT summaries
            prompt = f""" 두 텍스트를 종합하여 다음 항목을 중심으로 회사의 IR 메시지를 완벽하게 이해하고 요약해 주세요.
            
            1. 핵심 사업 및 제품/서비스: 회사의 주요 사업 영역과 핵심 제품/서비스는 무엇인가요?
            2. 시장 경쟁력: 시장에서 회사의 독점적인 강점은 무엇이며, 경쟁사와 비교했을 때의 차별점은 무엇인가요?
            3. 재무 성과 및 성장 전략: 최근 재무 성과는 어떠하며, 향후 성장을 위한 구체적인 전략은 무엇인가요?
            4. 투자 매력 포인트: 투자자들이 이 회사에 투자해야 하는 가장 강력한 이유는 무엇인가요? 프레젠테이션과 스크립트에서 강조된 주요 성장 동력(growth driver)을 중심으로 설명해 주세요.
            5. 질의응답 예측: 투자자들이 궁금해할 만한 예상 질문 3가지와 각 질문에 대한 답변을 준비해 주세요.
        
            # 입력 텍스트
            - IR 프레젠테이션 자료 요약: {IR_summarize.summary}
            - IR 발표 스크립트 요약: {SCRIPT_summarize.summary}
            """
            summary = self.script_analysis_agent.run(prompt, temperature=0.3)
        elif ir_exist:
            summary = IR_summarize.summary
        elif script_exist:
            summary = SCRIPT_summarize.summary
        else:
            print("IR.pdf와 SCRIPT.pdf 파일이 모두 존재하지 않습니다. IR 분석을 건너뜁니다.")
            return None

        # Save IR summary to markdown file
        # create out_dir if not exists
        os.makedirs(out_dir, exist_ok=True)
        with open(f'{out_dir}/ir_summary.md', 'w', encoding='utf-8') as md_file:
            md_file.write(summary)

        # print summary
        print(f'\nIR 자료 분석 결과:\n{summary[:500]}\n')

        return summary
