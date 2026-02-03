import os

import requests
import OpenDartReader
from datetime import timedelta, datetime

from unstructured.partition.html import partition_html

from src.tools.agents import Agent
from src.tools.summarizer import Summarizer
from src.tools.table_parser import chunk_elements
from src.tools.human_interrupt import HumanEditor


class BusinessAnalyst:
    def __init__(self, openai_key, dart_key, model='gpt-4.1-mini'):
        print("\n\n👩‍⚕️사업보고서 분석가를 불러옵니다.")
        self.dart = OpenDartReader(dart_key)
        optional_prompt = ('한 기의 실적은 1년(12개월) 누적, 반기 실적은 6개월 누적, 분기 실적은 3개월 누적을 의미합니다.'
                           '따라서 반기 실적을 한 기 실적과 비교할 때에는 1년 치 실적에서 최근 6개월 치 실적을 빼서 비교해야 합니다.'
                           '분기 실적을 한 기 실적과 비교할 때에는 1년 치 실적에서 최근 9개월 치 실적을 빼서 비교해야 합니다.')
        self.summarizer = Summarizer(apikey=openai_key, model=model, chunk_tokens=3000, target_summary_tokens=2000, optional_prompt=optional_prompt)
        self.human_editor = HumanEditor(openai_key, model)

    def run(self, company_info, out_dir=None):
        code = company_info['stock_code']
        if out_dir is None:
            out_dir = f'./data/A{code}_summary'

        # if output already exists, read and load file
        if os.path.exists(f'{out_dir}/company_business.md'):
            print(f"사업보고서 요약이 이미 존재합니다: {out_dir}/company_business.md")
            with open(f'{out_dir}/company_business.md', 'r', encoding='utf-8') as md_file:
                return md_file.read()

        # 사업보고서 목록 조회 (최근 5년)
        print(f"사업보고서 조회: {company_info['corp_name']} ({code})")

        startdate = datetime.today() - timedelta(days=150)  # 1년 전부터 시작
        reports = self.dart.list(code, start=startdate.strftime("%Y-%m-%d"), kind='A', final=True)
        print(reports)

        summarize = ""
        if not reports.empty:
            # 가장 최근 보고서 선택 (접수일자 기준)
            latest_report = reports.sort_values('rcept_dt', ascending=False).iloc[0]
            print(f"가장 최근 보고서: {latest_report['report_nm']} ({latest_report['rcept_dt']})")

            # 최근 보고서 원문 다운로드
            rcept_no = latest_report['rcept_no']
            sub_doc = self.dart.sub_docs(rcept_no)

            buss_summary = sub_doc[sub_doc.title.str.contains('사업의')].iloc[0]
            page = requests.get(buss_summary.url, headers={'User-Agent': 'Mozilla/5.0'})
            elements = partition_html(text=page.text, )
            chunks = chunk_elements(elements)

            summarize = self.summarizer.run(chunks)

        # confirm final report with human interruption
        summarize.summary = self.human_editor.run(summarize.summary)

        os.makedirs(out_dir, exist_ok=True)
        with open(f'{out_dir}/company_business.md', 'w', encoding='utf-8') as md_file:
            md_file.write(summarize.summary)

        return summarize.summary