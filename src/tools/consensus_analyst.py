import os
from glob import glob

import pandas as pd

from src.tools.agents import Agent


class ConsensusAnalyst:
    def __init__(self, openai_key):
        print("\n\n👩‍🏫컨센서스 분석가를 불러옵니다.")
        self.tableagent = Agent(
            api_key=openai_key,
            name="TableAgent",
            description="당신은 표를 분석하는 전문가입니다. 셀 내용을 그대로 재현하지 말고, 주요 결론(지표, 추세, 극값, 변화량, 주목할 만한 비교)을 설명하십시오.",
            model="gpt-4.1-mini"
        )

    def run(self, company_info, out_dir=None):
        """
        미래 가이던스 데이터를 읽고 분석하여 markdown 파일로 저장하는 함수

        Args:
            fncode: 회사 코드 (예: A381970)
            out_dir: 출력 디렉토리

        Returns:
            분석 결과 텍스트
        """
        code = company_info['stock_code']
        if out_dir is None:
            out_dir = f'./data/A{code}_summary'

        print(f"미래 가이던스 분석: {company_info['corp_name']} ({code})")

        try:
            # read earning_report.md file
            with open(f'{out_dir}/earnings_report.md', 'r', encoding='utf-8') as md_file:
                earnings_analysis = md_file.read()

            # past sheet 읽기
            sales_past_data = pd.read_excel(f'{out_dir}/IS.xlsx', sheet_name='sales', header=9, index_col=1).iloc[:, -1:]
            op_past_data = pd.read_excel(f'{out_dir}/IS.xlsx', sheet_name='op', header=9, index_col=1).iloc[:, -1:]
            income_past_data = pd.read_excel(f'{out_dir}/IS.xlsx', sheet_name='income', header=9, index_col=1).iloc[:, -1:]
            past_data = pd.concat([sales_past_data, op_past_data, income_past_data], axis=1)
            past_data.columns = ['매출액(백만원)', '영업이익(백만원)', '지배순이익(백만원)']

            # future sheet 읽기
            future_data = pd.read_excel(f'{out_dir}/IS.xlsx', sheet_name='future', header=9)
            future_data.index = future_data['Period']
            future_data = future_data.pivot(columns='Name', values=future_data.columns[-1:])
            future_data.columns = future_data.columns.droplevel(0) + '(백만원)'

            # 데이터 전처리 - NaN 값 처리
            future_data = future_data.dropna(how='all')  # 모든 값이 NaN인 행 제거
            future_data = future_data.fillna('-')  # 남은 NaN을 '-'로 대체

            if future_data.empty:
                print("Warning: Future sheet is empty")
                future_analysis = "미래 가이던스 데이터가 없습니다."
                # create out_dir if not exists
                os.makedirs(out_dir, exist_ok=True)
                with open(f'{out_dir}/consensus_analysis.md', 'w', encoding='utf-8') as md_file:
                    md_file.write(future_analysis)
                return future_analysis
            else:
                future_data_md = future_data.to_markdown()

            # 미래 가이던스 분석 프롬프트 생성 - 수치 중심 분석
            future_analysis_prompt = f"""
            회사명: {company_info['corp_name']}
    
            [다음 분기 가이던스 데이터]
            {future_data_md}
    
            [현재 분기 실적 발표 데이터]
            {earnings_analysis}
    
            [과거 실적(지난 분기부터) 데이터]
            {past_data.to_markdown()}
    
            분석 지침 - 수치 중심 분석:
            미래 가이던스 데이터를 기준으로 향후 재무 성과에 대해 전망하시오.
            1. **핵심 수치 추출 및 나열**:
               - 매출액, 영업이익, 순이익, EPS 등 주요 지표별 구체적 수치 명시
               - 각 항목별 절대 금액(백만원) 및 비율(%) 정확히 표시
    
            2. **성장률 계산 및 분석**:
               - 전년 동기 대비(YoY) 성장률 계산: ((당기-전년)/전년) × 100
               - 전분기 대비(QoQ) 성장률 계산: ((당기-전분기)/전분기) × 100
               - 각 지표별 성장률을 표 형식으로 정리
    
            3. **추세 분석**:
               - 분기별/연간 성장률 추세 (가속/둔화/안정/반전)
               - 계절성 패턴 수치적 분석
               - 성장률 변곡점 식별 및 수치적 근거 제시
    
            4. **수익성 지표 분석**:
               - 영업이익률 = (영업이익/매출) × 100
               - 순이익률 = (순이익/매출) × 100
               - 각 분기별 수익성 지표 변화 수치 계산
    
            출력 형식:
            ## 1. 다음 분기 가이던스 데이터 요약
            - 매출: X백만원 (전년대비 +/-X.X%)
            - 영업이익: X백만원 (전년대비 +/-X.X%)
            - 순이익: X백만원 (전년대비 +/-X.X%)
    
            ## 2. 성장률 분석표
            | 항목 | 당기 | 전년동기 | YoY(%) | 전분기 | QoQ(%) |
            |------|------|----------|--------|--------|--------|
            | 매출 | X | X | X.X | X | X.X |
    
            ## 3. 수익성 추세
            - 영업이익률: X.X% (전년 X.X%p 변화)
            - 순이익률: X.X% (전년 X.X%p 변화)
    
            ## 4. 성장률 추세 분석
            - 각 지표별 분기 성장률 변화 패턴을 수치로 명시
            """

            # AI 에이전트를 사용한 분석
            future_analysis = self.tableagent.run(
                prompt=future_analysis_prompt,
                temperature=0.2
            )

            # 분석 결과를 markdown 파일로 저장
            # create out_dir if not exists
            os.makedirs(out_dir, exist_ok=True)
            with open(f'{out_dir}/consensus_analysis.md', 'w', encoding='utf-8') as md_file:
                md_file.write(future_analysis)

            # print 500 characters of future_analysis
            print(f"\n미래 가이던스 분석 결과:\n{future_analysis[:500]}...\n")

            return future_analysis

        except FileNotFoundError:
            error_msg = f"Error: Excel 파일을 찾을 수 없습니다: {out_dir}/IS.xlsx"
            print(error_msg)
            return error_msg
        except ValueError as e:
            error_msg = f"Error: 'future' 시트를 찾을 수 없습니다: {e}"
            print(error_msg)
            return error_msg