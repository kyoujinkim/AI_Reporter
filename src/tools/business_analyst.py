import os

import requests
import OpenDartReader
from datetime import timedelta, datetime

from unstructured.partition.html import partition_html

from src.tools.summarizer import Summarizer
from src.tools.table_parser import chunk_elements


class BusinessAnalyst:
    def __init__(self, openai_key, dart_key):
        print("\n\n👩‍⚕️사업보고서 분석가를 불러옵니다.")
        self.dart = OpenDartReader(dart_key)
        self.summarizer = Summarizer(apikey=openai_key, chunk_tokens=3000, target_summary_tokens=1000)

    def run(self, company_info, out_dir=None):
        code = company_info['stock_code']
        if out_dir is None:
            out_dir = f'./data/A{code}_summary'

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

            # Save summary to markdown file
            # create out_dir if not exists
            os.makedirs(out_dir, exist_ok=True)
            with open(f'{out_dir}/company_business.md', 'w', encoding='utf-8') as md_file:
                md_file.write(summarize.summary)

        return summarize