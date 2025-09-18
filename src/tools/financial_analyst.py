import os

import pandas as pd

from src.tools.agents import Agent


class FinancialAnalyst:
    def __init__(self, openai_key):
        print("\n\n👨‍💻재무제표 분석가를 불러옵니다.")
        self.tableagent = Agent(
            api_key=openai_key,
            name="TableAgent",
            description="당신은 표를 분석하는 전문가입니다. 셀 내용을 그대로 재현하지 말고, 주요 결론(지표, 추세, 극값, 변화량, 주목할 만한 비교)을 설명하십시오.",
            model="gpt-4.1-mini"
        )

    def run(self,company_info, out_dir=None):
        code = company_info['stock_code']
        if out_dir is None:
            out_dir = f'./data/A{code}_summary'

        print(f"재무제표 분석: {company_info['corp_name']} ({code})")
        # select only last column
        sales = pd.read_excel(f'{out_dir}/IS.xlsx', sheet_name='sales', header=9, index_col=1).iloc[:, -1:]
        sales.columns = ['매출액(백만원)']
        op = pd.read_excel(f'{out_dir}/IS.xlsx', sheet_name='op', header=9, index_col=1).iloc[:, -1:]
        op.columns = ['영업이익(백만원)']
        income = pd.read_excel(f'{out_dir}/IS.xlsx', sheet_name='income', header=9, index_col=1).iloc[:, -1:]
        income.columns = ['지배순이익(백만원)']

        # 1. 데이터 준비
        financial_summary = f"""
        회사명: {company_info['corp_name']}
    
        [매출 추이]
        {sales.to_markdown()}
    
        [영업이익 추이]
        {op.to_markdown()}
    
        [지배순이익 추이]
        {income.to_markdown()}
    
        분석 지침:
        1. 각 항목별 시계열 추세 분석 (증가/감소, 변동 폭, 패턴, 전환점)
        2. 전년 동기 및 직전 분기 대비 변화율 계산
        3. 영업이익률, 순이익률 변화 및 의미 분석
        4. 눈에 띄는 이상치나 급격한 변화가 있다면 원인 추정
        5. 투자자 관점에서 주목할 인사이트 제시
        6. "요약 → 세부 분석 → 주요 수치" 형식으로 작성
        """

        # feed in to llm, and analyze the financial data
        financial_analysis = self.tableagent.run(
            prompt=financial_summary,
            temperature=0.2
        )

        # Save financial analysis to markdown file
        # create out_dir if not exists
        os.makedirs(out_dir, exist_ok=True)
        with open(f'{out_dir}/financial_analysis.md', 'w', encoding='utf-8') as md_file:
            md_file.write(financial_analysis)

        return financial_analysis