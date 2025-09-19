import os

import pandas as pd
from datetime import timedelta, datetime

import requests
import OpenDartReader
from unstructured.partition.html import partition_html

from src.tools.agents import Agent
from src.tools.table_parser import chunk_elements


class EarningsAnalyst:
    def __init__(self, openai_key, dart_key):
        print("\n\n👨‍💼기업실적 분석가를 불러옵니다.")
        self.tableagent = Agent(
            api_key=openai_key,
            name="TableAgent",
            description="당신은 표를 분석하는 전문가입니다. 셀 내용을 그대로 재현하지 말고, 주요 결론(지표, 추세, 극값, 변화량, 주목할 만한 비교)을 설명하십시오.",
            model="gpt-4.1-mini"
        )
        self.dart = OpenDartReader(dart_key)

    def run(self, company_info, out_dir=None):
        code = company_info['stock_code']
        if out_dir is None:
            out_dir = f'./data/A{code}_summary'

        print(f"실적발표 분석: {company_info['corp_name']} ({code})")

        consensus_date = pd.read_excel(f'{out_dir}/IS.xlsx', sheet_name='consensus', nrows=11, index_col=0).iloc[-1, -1]
        consensus = pd.read_excel(f'{out_dir}/IS.xlsx', sheet_name='consensus', header=13, index_col=0)
        consensus.columns = f'{consensus_date}' + consensus.columns + ' 컨센서스(백만원)'
        # 데이터 전처리 - NaN 값 처리
        consensus = consensus.dropna(how='all')  # 모든 값이 NaN인 행 제거
        consensus = consensus.fillna('-')  # 남은 NaN을 '-'로 대체
        if consensus.empty:
            print("Warning: Consensus sheet is empty")
            consensus_ts_md = "과거 컨센서스 데이터가 없습니다."
            consensus_md = "최근 컨센서스 데이터가 없습니다."
        else:
            consensus_ts_md = consensus.drop_duplicates().to_markdown()
            consensus_md = consensus.iloc[-1:].to_markdown()

        earnings_text = self.earnings_report(code)
        # save earnings_text to md file
        with open(f'{out_dir}/earnings_report.md', 'w', encoding='utf-8') as md_file:
            md_file.write(earnings_text)

        # 3. 통합 분석 프롬프트
        prompt = f"""
        회사명: {company_info['corp_name']}
    
        [과거 컨센서스 추이]
        {consensus_ts_md}
    
        [최근 컨센서스]
        {consensus_md}
    
        [실적발표]
        {earnings_text}
    
        분석 지침:
        1. 컨센서스의 시계열 추세 분석 (증가/감소, 변동 폭, 추세 전환점 등)
        2. 마지막 컨센서스 수치 평가 (이전 대비 변화 요약)
        3. 실적발표와 마지막 컨센서스 비교 (차이의 원인 및 규모)
        4. 주목할 만한 변화나 이슈 정리
        5. 필요한 경우 표/목록 형식으로 명확하게 제시
        * 실적발표 수치는 반기 누적이 아닌 분기별 수치를 중심으로 분석
        """

        # 4. 한 번에 실행
        response = self.tableagent.run(
            prompt=prompt,
            temperature=0.2
        )

        # Save earnings analysis to markdown file
        # create out_dir if not exists
        os.makedirs(out_dir, exist_ok=True)
        with open(f'{out_dir}/earnings_analysis.md', 'w', encoding='utf-8') as md_file:
            md_file.write(response)

        # print 500 characters of response
        print(f'\n실적발표 분석 결과:\n{response[:500]}...\n')

        return response

    def earnings_report(self, code):
        print(f"실적발표 조회: {code}")
        # Read earnings report
        startdate = datetime.today() - timedelta(days=60)  # 1년 전부터 시작
        earnings = self.dart.list(code, start=startdate.strftime("%Y-%m-%d"), kind='I', final=True)
        earnings = earnings[earnings['report_nm'].str.contains('영업\\(잠정\\)실적', regex=True)]
        if len(earnings) > 0:
            latest_earnings = earnings.sort_values('rcept_dt', ascending=False).iloc[0]
            xml_text = self.dart.document(latest_earnings['rcept_no'])
            elements = partition_html(text=xml_text, xml_keep_tags=True)
            print("잠정 실적발표가 있습니다.")
            return "\n".join([str(e) for e in elements if hasattr(e, 'text') and e.text.strip() != ''])
        else:
            print("잠정 실적발표가 없습니다.")

        # if no earnings report, search for the latest quarterly report
        qreports = self.dart.list(code, start=startdate.strftime("%Y-%m-%d"), kind='Q', final=True)
        areports = self.dart.list(code, start=startdate.strftime("%Y-%m-%d"), kind='A', final=True)
        reports = pd.concat([qreports, areports])
        # find (YYYY.MM) in report_nm and add new columns
        reports['report_ym'] = reports['report_nm'].str.extract(r'(\d{4}\.\d{1,2})')[0]
        reports = reports.sort_values('report_ym', ascending=False)
        # if no report, raise error
        if reports.empty:
            print("최근 발표된 보고서가 없습니다.")
            raise ValueError("최근 보고서가 없습니다.")
        latest_report = reports.sort_values('rcept_dt', ascending=False).iloc[0]
        text = self.get_income_statement(latest_report['rcept_no'])

        return text

    def get_income_statement(self, rcept_no):
        # 최근 보고서 원문 다운로드
        sub_doc = self.dart.sub_docs(rcept_no)

        inc_stat = sub_doc[sub_doc.title.str.contains('재무제표')]
        inc_stat = inc_stat[~inc_stat.title.str.contains('주석')]
        for i, row in inc_stat.iterrows():
            page = requests.get(row.url, headers={'User-Agent': 'Mozilla/5.0'})
            if len(page.text) > 1500:
                break

        elements = partition_html(text=page.text, )
        chunks = chunk_elements(elements)
        # chunks = list of sublist of elements
        # join the sublist elements to text
        joined_chunk = []
        for chunk in chunks:
            joined_chunk.append("\n".join([str(e) for e in chunk if hasattr(e, 'text') and e.text.strip() != '']))
        # left chunk which contains "손익계산서"
        filtered_chunks = [c for c in joined_chunk if "손익계산서" in c or "손익계산표" in c]

        return '\n'.join(filtered_chunks)