import os
from glob import glob

import pandas as pd
from pydantic import BaseModel

from src.tools.agents import Agent

class Estimation(BaseModel):
    step1: str
    step2: str
    step3: str
    #conclusion: str

class EstimateAnalyst:
    def __init__(self, openai_key):
        print("\n\n🤴미래 실적 예측가를 불러옵니다.")
        self.estimatoragent = Agent(
            api_key=openai_key,
            name="EstimatorAgent",
            description="당신은 재무 예측 전문가입니다. 주어진 데이터를 바탕으로 합리적인 추정치를 계산하십시오.",
            model="gpt-4.1-mini"
        )

    def run(self, company_info, out_dir=None):
        """
        미래 재무 성과를 예측하는 함수
        """
        code = company_info['stock_code']
        if out_dir is None:
            out_dir = f'./data/A{code}_summary'

        print(f"미래 가이던스 분석: {company_info['corp_name']} ({code})")

        try:
            # read earning_report.md file
            with open(f'{out_dir}/earnings_report.md', 'r', encoding='utf-8') as md_file:
                earnings_analysis = md_file.read()
            with open(f'{out_dir}/ir_summary.md', 'r', encoding='utf-8') as f:
                ir_analysis = f.read()
            with open(f'{out_dir}/news_analysis.md', 'r', encoding='utf-8') as f:
                news_analysis = f.read()

            # past sheet 읽기
            sales_past_data = pd.read_excel(f'{out_dir}/IS.xlsx', sheet_name='sales', header=9, index_col=1).iloc[:, -1:]
            op_past_data = pd.read_excel(f'{out_dir}/IS.xlsx', sheet_name='op', header=9, index_col=1).iloc[:, -1:]
            income_past_data = pd.read_excel(f'{out_dir}/IS.xlsx', sheet_name='income', header=9, index_col=1).iloc[:, -1:]
            past_data = pd.concat([sales_past_data, op_past_data, income_past_data], axis=1)
            past_data.columns = ['매출액(백만원)', '영업이익(백만원)', '지배순이익(백만원)']

            guidance_estimation_prompt = f"""
            당신은 현재 분기 IR 자료와 과거 실적 추세를 기반으로 다음 분기 실적을 매우 정밀하게 추론하는 전문 금융 분석 AI Agent입니다. 제공된 모든 정보를 종합하여, 다음과 같은 세 가지 단계로 분석을 진행하고 최종 결과를 도출해 주세요.

            현재 분기 실적 발표 데이터 : '{earnings_analysis}'
            과거 실적 데이터 : '{past_data.to_markdown()}'
            IR 요약 : '{ir_analysis}'
            뉴스 요약 : '{news_analysis}'

            ### step1: 핵심 지표 분석 및 추세 파악

            - **현재 분기 실적 분석:** '현재 분기 실적 발표 데이터'를 철저히 분석하여, 주요 재무 지표(매출, 영업이익, 순이익 등)가 전년동기/전분기 대비 어떻게 변화했는지와 서프라이즈/쇼크 발생 사유를 파악하세요.
            - **과거 실적 추세 파악:** 제공된 '과거 실적 데이터'를 기반으로, 계절성, 성장률, 수익성 추이 등 회사의 장기적인 재무 추세를 파악하세요. 특히, 어떤 지표들이 지속적인 성장 또는 하락 추세를 보였는지 식별하세요.

            ### step2: 질적 정보(IR & 뉴스)와 정량적 정보(실적)의 연관성 분석

            - **IR 메시지 통합:** 'IR 요약'에 담긴 회사의 다음 분기 가이던스, 핵심 전략, 시장 전망 등을 1단계에서 파악한 정량적 실적 추세와 연결하여 해석하세요. 예를 들어, 회사가 '신규 사업 확장'을 강조했다면, 이것이 매출액 증가 추세에 어떤 영향을 미칠지 논리적으로 연결해 보세요.
            - **외부 환경 영향 분석:** '뉴스 요약'에 나타난 시장 동향, 경쟁사 동향, 규제 변화 등 외부 환경 요인이 회사의 과거 및 현재 실적에 어떻게 영향을 미쳤고, 앞으로 어떤 영향을 줄지 분석하세요.

            ### step3: 다음 분기 실적 추론 및 근거 제시

            - **최종 추론:** 1단계와 2단계의 분석 결과를 모두 종합하여 다음 분기 실적 추정치를 구체적인 수치로 제시하세요.
            - **추론 근거:** 각 지표를 추론한 핵심 근거를 명확하고 간결하게 설명하세요. 단순히 숫자를 제시하는 것이 아니라, "왜 그렇게 조정했는지"에 대한 논리적 이유를 IR 메시지, 과거 추세, 뉴스 요약 등 제공된 정보와 연관지어 설명해야 합니다.

            **회사명:** `{company_info['corp_name']}`
            """

            estimation = self.estimatoragent.run_with_structured_format(
                prompt=guidance_estimation_prompt,
                response_format=Estimation,
                temperature=0.2
            )

            # 분석 결과를 markdown 파일로 저장
            # concat estimation's step1, step2, step3
            estimation_md = f"""## 미래 실적 예측 결과\n\n
            ### Step 1: 핵심 지표 분석 및 추세 파악\n{estimation.step1}\n\n
            ### Step 2: 질적 정보(IR & 뉴스)와 정량적 정보(실적)의 연관성 분석\n{estimation.step2}\n\n
            ### Step 3: 다음 분기 실적 추론 및 근거 제시\n{estimation.step3}\n"""
            # create out_dir if not exists
            os.makedirs(out_dir, exist_ok=True)
            with open(f'{out_dir}/estimate_analysis.md', 'w', encoding='utf-8') as md_file:
                md_file.write(estimation_md)

            # print 500 characters of future_analysis
            print(f"\n미래 실적 예측 결과:\n{estimation_md[:500]}...\n")

            return estimation_md

        except FileNotFoundError:
            error_msg = f"Error: Excel 파일을 찾을 수 없습니다: {out_dir}/IS.xlsx"
            print(error_msg)
            return error_msg
        except ValueError as e:
            error_msg = f"Error: 'future' 시트를 찾을 수 없습니다: {e}"
            print(error_msg)
            return error_msg