import configparser
import os

import pandas as pd
from datetime import timedelta, datetime

import requests
import OpenDartReader
from unstructured.partition.html import partition_html

from src.tools.agents import Agent
from src.tools.human_interrupt import HumanEditor
from src.tools.table_parser import chunk_elements


class EarningsAnalyst:
    def __init__(self, openai_key, dart_key, model="gpt-4.1-mini"):
        print("\n\n👨‍💼기업실적 분석가를 불러옵니다.")
        self.tableagent = Agent(
            api_key=openai_key,
            name="TableAgent",
            description="당신은 표를 분석하는 전문가입니다. 셀 내용을 그대로 재현하지 말고, 주요 결론(지표, 추세, 극값, 변화량, 주목할 만한 비교)을 설명하십시오.",
            model=model
        )
        self.human_editor = HumanEditor(
            openai_key=openai_key,
            model=model,
            tools=[{'type':'web_search'}]
        )
        self.dart = OpenDartReader(dart_key)

    def run(self, company_info, out_dir=None):
        code = company_info['stock_code']
        if out_dir is None:
            out_dir = f'./data/A{code}_summary'

        # if earnings_analysis already exists, read and return
        if os.path.exists(f'{out_dir}/earnings_analysis.md'):
            with open(f'{out_dir}/earnings_analysis.md', 'r', encoding='utf-8') as md_file:
                response = md_file.read()
            print(f"실적발표 분석 결과가 이미 존재합니다: {company_info['corp_name']} ({code})")
            return response, True  # consensus_flag is True since file exists

        print(f"실적발표 분석: {company_info['corp_name']} ({code})")

        consensus_date = pd.read_excel(f'{out_dir}/IS.xlsx', sheet_name='consensus', nrows=11, index_col=0).iloc[-1, -1]
        consensus = pd.read_excel(f'{out_dir}/IS.xlsx', sheet_name='consensus', header=13, index_col=0)
        consensus.columns = f'{consensus_date}' + consensus.columns + ' 컨센서스(백만원)'
        # 데이터 전처리 - NaN 값 처리
        consensus = consensus.dropna(how='all')

        # 특정 컨센서스가 없는 경우, 추정치를 생성해야하므로 플래그 생성
        if len(consensus.dropna(axis=1, how='all').columns) != 3:
            # 무언가 데이터가 아예 없는 셀이 존재
            print("Warning: Some Consensus data does not exist")
            consensus_flag = False
        else:
            consensus_flag = True

        # 모든 값이 NaN인 행 제거
        consensus = consensus.fillna('-')  # 남은 NaN을 '-'로 대체
        # 열별로 데이터가 (-)으로만 구성된 경우 데이터가 없는 것으로 간주

        if consensus.empty:
            print("Warning: Consensus sheet is empty")
            consensus_ts_md = "과거 컨센서스 데이터가 없습니다."
            consensus_md = "최근 컨센서스 데이터가 없습니다."
        else:
            consensus_ts_md = consensus.drop_duplicates().to_markdown()
            consensus_md = consensus.iloc[-1:].to_markdown()

        # 당해 누적 실적
        earnings_cum = pd.read_excel(f'{out_dir}/IS.xlsx', sheet_name='earnings_cum', header=0, index_col=0)
        earnings_cum_md = earnings_cum.to_markdown()

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
        
        [당해 누적 실적]
        {earnings_cum_md}
    
        [실적발표]
        {earnings_text}
    
        분석 지침:
        1. 컨센서스의 시계열 추세 분석 (증가/감소, 변동 폭, 추세 전환점 등)
        2. 마지막 컨센서스 수치 평가 (이전 대비 변화 요약)
        3. 실적발표와 마지막 컨센서스 비교 (차이의 원인 및 규모)
        ** 실적발표에서는 매출액, 영업이익, 지배주순이익 중심으로 분석
        4. 주목할 만한 변화나 이슈 정리
        5. 필요한 경우 표/목록 형식으로 명확하게 제시
        * 실적발표 수치는 반기 누적이 아닌 분기별 수치를 중심으로 분석. 분기별 수치가 없는 경우, 당해 누적 수치를 사용하여 분기별 수치를 추정
        """

        # 4. 한 번에 실행
        response = self.tableagent.run(
            prompt=prompt,
            temperature=0.2
        )

        self.human_editor.editagent.inherit_messages(self.tableagent)
        response = self.human_editor.run(response)

        # Save earnings analysis to markdown file
        # create out_dir if not exists
        os.makedirs(out_dir, exist_ok=True)
        with open(f'{out_dir}/earnings_analysis.md', 'w', encoding='utf-8') as md_file:
            md_file.write(response)

        return response, consensus_flag

    def earnings_report(self, code):
        print(f"실적발표 조회: {code}")
        # Read earnings report
        startdate = datetime.today() - timedelta(days=60)  # 1년 전부터 시작
        earnings = self.dart.list(code, start=startdate.strftime("%Y-%m-%d"), kind='I', final=True)
        earnings_rpt = earnings[earnings['report_nm'].str.contains('영업\\(잠정\\)실적', regex=True)]
        earnings_chg = earnings[earnings['report_nm'].str.contains('매출액또는손익구조', regex=True)]
        if len(earnings_rpt) > 0:
            latest_earnings = earnings_rpt.sort_values('rcept_dt', ascending=False).iloc[0]
            xml_text = self.dart.document(latest_earnings['rcept_no'])
            elements = partition_html(text=xml_text, xml_keep_tags=True)
            print("잠정 실적발표가 있습니다.")
            return "\n".join([str(e) for e in elements if hasattr(e, 'text') and e.text.strip() != ''])
        elif len(earnings_chg) > 0:
            latest_earnings = earnings_chg.sort_values('rcept_dt', ascending=False).iloc[0]
            xml_text = self.dart.document(latest_earnings['rcept_no'])
            elements = partition_html(text=xml_text, xml_keep_tags=True)
            print("매출액 또는 손익구조 30% 이상 변동 공시가 있습니다.")
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

if __name__ == "__main__":
    config_file = "D:/config.ini"
    config = configparser.ConfigParser()
    config.read(config_file)
    dart_key = config.get("dart", "API_KEY")
    ai_key = config.get("openai", "API_KEY")
    tavily_api_key = config.get("tavily", "API_KEY_NH")

    earnings_analyst = EarningsAnalyst(openai_key=ai_key, dart_key=dart_key)

    # Example company: Samsung Electronics (005930)
    dart = OpenDartReader(dart_key)
    company_info = dart.company("041920")
    company_info['industry'] = "심장제세동기"

    earnings_analysis, consensus_flag = earnings_analyst.run(company_info, out_dir=r'C:\Users\NHWM\PycharmProjects\AI_Reporter\data')
    print(earnings_analysis)