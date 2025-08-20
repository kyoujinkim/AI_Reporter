import configparser
from datetime import timedelta, datetime
from glob import glob

import pandas as pd
import requests
from unstructured.partition.html import partition_html
from src.tools.table_parser import chunk_elements
from src.tools.summarizer import Summarizer
from src.tools.agents import Agent
from src.tools.pdf_parser import PDFParser

import OpenDartReader

code = '381970'
fncode = 'A' + code

config_file = "D:/config.ini"
config = configparser.ConfigParser()
config.read(config_file)
dart_key = config.get("dart", "API_KEY")
ai_key = config.get("openai", "API_KEY")

dart = OpenDartReader(dart_key)
summarizer = Summarizer(apikey=ai_key, chunk_tokens=3000, target_summary_tokens=1000)
pdfparser = PDFParser(api_key=ai_key)

tableagent = Agent(
    api_key=ai_key,
    name="TableAgent",
    description="당신은 표를 분석하는 전문가입니다. 셀 내용을 그대로 재현하지 말고, 주요 결론(지표, 추세, 극값, 변화량, 주목할 만한 비교)을 설명하십시오.",
    model="gpt-5-mini"
)
iragent = Agent(
    api_key=ai_key,
    name="IRAgent",
    description="당신은 기업의 IR 분석 전문가입니다. 사업보고서, 재무제표, 실적발표 등을 분석하고 요약하는 데 능숙합니다. 내용을 그대로 재현하지 말고, 주요 결론(지표, 추세, 극값, 변화량, 주목할 만한 비교)을 설명하십시오.",
    model="gpt-5-mini"
)

company_info = dart.company(code)

def read_annual_report(code, out_dir='./data/summary'):
    # 사업보고서 목록 조회 (최근 5년)
    startdate = datetime.today() - timedelta(days=150)  # 1년 전부터 시작
    reports = dart.list(code, start=startdate.strftime("%Y-%m-%d"), kind='A', final=True)
    print(reports)

    if not reports.empty:
        # 가장 최근 보고서 선택 (접수일자 기준)
        latest_report = reports.sort_values('rcept_dt', ascending=False).iloc[0]
        print(f"가장 최근 보고서: {latest_report['report_nm']} ({latest_report['rcept_dt']})")

        # 최근 보고서 원문 다운로드
        rcept_no = latest_report['rcept_no']
        sub_doc = dart.sub_docs(rcept_no)

        buss_summary = sub_doc[sub_doc.title.str.contains('사업의')].iloc[0]
        page = requests.get(buss_summary.url, headers={'User-Agent': 'Mozilla/5.0'})
        elements = partition_html(text=page.text, )
        chunks = chunk_elements(elements)

        summarize = summarizer.run(chunks)

        # Save summary to markdown file
        with open(f'{out_dir}/company_business.md', 'w', encoding='utf-8') as md_file:
            md_file.write(summarize.summary)

    return summarize

def analyze_financial_data(fncode, out_dir='./data/summary'):
    # data에서 '{code}_IS.xlsx'에 재무데이터 읽어오기(consensus, sales, op, income)
    consensus = pd.read_excel(f'./data/{fncode}_IS.xlsx', sheet_name='consensus', header=13, index_col=0)
    # select only last column
    sales = pd.read_excel(f'./data/{fncode}_IS.xlsx', sheet_name='sales', header=9, index_col=1).iloc[:, -1:]
    sales.columns = ['매출액(백만원)']
    op = pd.read_excel(f'./data/{fncode}_IS.xlsx', sheet_name='op', header=9, index_col=1).iloc[:, -1:]
    op.columns = ['영업이익(백만원)']
    income = pd.read_excel(f'./data/{fncode}_IS.xlsx', sheet_name='income', header=9, index_col=1).iloc[:, -1:]
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
    financial_analysis = tableagent.run(
        prompt=financial_summary,
        temperature=0.2
    )

    # Save financial analysis to markdown file
    with open(f'{out_dir}/financial_analysis.md', 'w', encoding='utf-8') as md_file:
        md_file.write(financial_analysis)

    return financial_analysis

def earnings_report(code):
    # Read earnings report
    startdate = datetime.today() - timedelta(days=60)  # 1년 전부터 시작
    earnings = dart.list(code, start=startdate.strftime("%Y-%m-%d"), kind='I', final=True)
    earnings = earnings[earnings['report_nm'].str.contains('영업\(잠정\)실적')]
    if len(earnings)>0:
        latest_earnings = earnings.sort_values('rcept_dt', ascending=False).iloc[0]
        xml_text = dart.document(latest_earnings['rcept_no'])
        elements = partition_html(text=xml_text, xml_keep_tags=True)
    else:
        print("실적발표가 없습니다.")
        return None

    return elements

def analyze_earnings(code, out_dir='./data/summary'):
    consensus_date = pd.read_excel(f'./data/{fncode}_IS.xlsx', sheet_name='consensus', nrows=11, index_col=0).iloc[-1, -1]
    consensus = pd.read_excel(f'./data/{fncode}_IS.xlsx', sheet_name='consensus', header=13, index_col=0)
    consensus.columns = f'{consensus_date}' + consensus.columns + ' 컨센서스(백만원)'
    earnings = earnings_report(code)
    earnings_text = "\n".join([str(e) for e in earnings if hasattr(e, 'text') and e.text.strip() != ''])

    # 3. 통합 분석 프롬프트
    prompt = f"""
    회사명: {company_info['corp_name']}

    [컨센서스 추이]
    {consensus.drop_duplicates().to_markdown()}
    
    [마지막 컨센서스]
    {consensus.iloc[-1:].to_markdown()}

    [실적발표]
    {earnings_text}

    분석 지침:
    1. 컨센서스의 시계열 추세 분석 (증가/감소, 변동 폭, 추세 전환점 등)
    2. 마지막 컨센서스 수치 평가 (이전 대비 변화 요약)
    3. 실적발표와 마지막 컨센서스 비교 (차이의 원인 및 규모)
    4. 주목할 만한 변화나 이슈 정리
    5. 필요한 경우 표/목록 형식으로 명확하게 제시
    """

    # 4. 한 번에 실행
    response = tableagent.run(
        prompt=prompt,
        temperature=0.2
    )

    # Save earnings analysis to markdown file
    with open(f'{out_dir}/earnings_analysis.md', 'w', encoding='utf-8') as md_file:
        md_file.write(response)

    return response

def read_ir_report(fncode, out_dir='./data/summary'):
    # IR 보고서 목록 조회 (최근 5년)
    pdfparser.parse_pdf(f'./data/{fncode}_IR.pdf',
                        out_dir=out_dir,
                        #start_page=20,
                        #end_page=23,
                        )
    # read md file in markdown folder
    markdown_list = glob(f'{out_dir}/markdown/*.md')
    markdown_content = ""
    for md_file in markdown_list:
        with open(md_file, 'r', encoding='utf-8') as file:
            markdown_content += file.read() + "\n\n"
    summarize = summarizer.run_text(markdown_content, 4000)

    # Save IR summary to markdown file
    with open(f'{out_dir}/ir_summary.md', 'w', encoding='utf-8') as md_file:
        md_file.write(summarize.summary)

    return summarize

if __name__ == "__main__":
    # 회사 기본정보 조회

    # Read annual report and summarize
    comapny_business = read_annual_report(code, out_dir='./data/summary')
    #print(comapny_business.summary)

    # Read financial data and analyze
    financial_analysis = analyze_financial_data(fncode, out_dir='./data/summary')
    #print(financial_analysis)

    # Read earnings report
    earnings_analysis = analyze_earnings(code, out_dir='./data/summary')
    #print(earnings_analysis)

    # Read IR report
    ir_summary = read_ir_report(fncode, out_dir='./data/summary')
    print(ir_summary.summary)

    # Process Deep Research with collected data(company_business, financial_analysis, earnings_analysis, ir_summary)
