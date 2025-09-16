import configparser
from datetime import timedelta, datetime
from glob import glob
from typing import Dict

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
tavily_api_key = config.get("tavily", "API_KEY_NH")

dart = OpenDartReader(dart_key)
summarizer = Summarizer(apikey=ai_key, chunk_tokens=3000, target_summary_tokens=1000)
pdfparser = PDFParser(api_key=ai_key)

tableagent = Agent(
    api_key=ai_key,
    name="TableAgent",
    description="당신은 표를 분석하는 전문가입니다. 셀 내용을 그대로 재현하지 말고, 주요 결론(지표, 추세, 극값, 변화량, 주목할 만한 비교)을 설명하십시오.",
    model="gpt-4.1-mini"
)
iragent = Agent(
    api_key=ai_key,
    name="IRAgent",
    description="당신은 기업의 IR 분석 전문가입니다. 사업보고서, 재무제표, 실적발표 등을 분석하고 요약하는 데 능숙합니다. 내용을 그대로 재현하지 말고, 주요 결론(지표, 추세, 극값, 변화량, 주목할 만한 비교)을 설명하십시오.",
    model="gpt-4.1-mini"
)

news_analysis_agent = Agent(
    api_key=ai_key,
    name="NewsAnalysisAgent",
    description="""당신은 뉴스 분석 전문가입니다.
    기업 관련 뉴스와 산업 뉴스를 분석하여 실적 분석에 도움이 되는 인사이트를 도출합니다.
    시장 동향, 경쟁사 현황, 산업 트렌드 등을 파악하여 기업의 실적과 전망에 미치는 영향을 분석합니다.""",
    model="gpt-4.1-mini"
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
    earnings = earnings[earnings['report_nm'].str.contains('영업\\(잠정\\)실적', regex=True)]
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

    [과거 컨센서스 추이]
    {consensus.drop_duplicates().to_markdown()}
    
    [최근 컨센서스]
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

def analyze_consensus(fncode, out_dir='./data/summary'):
    """
    미래 가이던스 데이터를 읽고 분석하여 markdown 파일로 저장하는 함수
    
    Args:
        fncode: 회사 코드 (예: A381970)
        out_dir: 출력 디렉토리
    
    Returns:
        분석 결과 텍스트
    """
    try:
        # future sheet 읽기
        future_data = pd.read_excel(f'./data/{fncode}_IS.xlsx', sheet_name='future', header=9)
        future_data.index = future_data['FPeriod']
        future_data = future_data.pivot(columns='Name', values=future_data.columns[-1:])
        future_data.columns = future_data.columns.droplevel(0) + '(백만원)'
        
        # 데이터가 비어있는지 확인
        if future_data.empty:
            print("Warning: Future sheet is empty")
            return "미래 가이던스 데이터가 없습니다."
        
        # 데이터 전처리 - NaN 값 처리
        future_data = future_data.dropna(how='all')  # 모든 값이 NaN인 행 제거
        future_data = future_data.fillna('-')  # 남은 NaN을 '-'로 대체
        
        # 미래 가이던스 분석 프롬프트 생성 - 수치 중심 분석
        future_analysis_prompt = f"""
        회사명: {company_info['corp_name']}
        
        [미래 가이던스 데이터]
        {future_data.to_markdown()}
        
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
        ## 1. 핵심 수치 요약
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
        future_analysis = tableagent.run(
            prompt=future_analysis_prompt,
            temperature=0.2
        )
        
        # 분석 결과를 markdown 파일로 저장
        with open(f'{out_dir}/consensus_analysis.md', 'w', encoding='utf-8') as md_file:
            md_file.write(future_analysis)

        return future_analysis
        
    except FileNotFoundError:
        error_msg = f"Error: Excel 파일을 찾을 수 없습니다: ./data/{fncode}_IS.xlsx"
        print(error_msg)
        return error_msg
    except ValueError as e:
        error_msg = f"Error: 'future' 시트를 찾을 수 없습니다: {e}"
        print(error_msg)
        return error_msg

def analyze_news(company_name: str, industry: str = "") -> str:
    """뉴스 검색 및 분석 통합 함수"""
    news_data = _search_news_with_tavily(company_name, industry)
    analysis = _analyze_news_impact(news_data, company_info)

    # Save news analysis to markdown file
    with open(f'./data/summary/news_analysis.md', 'w', encoding='utf-8') as md_file:
        md_file.write(analysis)

    return analysis

def _search_news_with_tavily(company_name: str, industry: str = "") -> Dict[str, str]:
    """Tavily API를 사용한 뉴스 검색"""
    if not tavily_api_key:
        return {"company_news": "뉴스 검색 불가: Tavily API 키 없음", "industry_news": "뉴스 검색 불가: Tavily API 키 없음"}

    news_data = {}

    # 기업 관련 뉴스 검색
    try:
        company_query = f"{company_name} 실적 earnings financial performance recent news"
        company_response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": tavily_api_key,
                "query": company_query,
                "search_depth": "basic",
                "include_answer": True,
                "include_raw_content": False,
                "max_results": 5,
                "include_domains": ["naver.com", "daum.net", "yonhapnews.co.kr", "einfomax.co.kr", "mk.co.kr",
                                    "sedaily.com"]
            },
            timeout=10
        )

        if company_response.status_code == 200:
            company_data = company_response.json()
            # 검색 결과를 텍스트로 정리
            company_articles = []
            for result in company_data.get('results', []):
                company_articles.append(
                    f"**{result.get('title', 'N/A')}**\n{result.get('content', 'N/A')[:300]}...\n출처: {result.get('url', 'N/A')}")

            news_data['company_news'] = "\n\n".join(
                company_articles) if company_articles else "기업 관련 뉴스를 찾을 수 없습니다."
        else:
            news_data['company_news'] = "기업 뉴스 검색 실패"

    except Exception as e:
        print(f"Warning: 기업 뉴스 검색 중 오류 발생: {e}")
        news_data['company_news'] = "기업 뉴스 검색 중 오류 발생"

    # 산업 관련 뉴스 검색
    try:
        if industry:
            industry_query = f"{industry} industry trends market outlook korea recent news"
        else:
            industry_query = f"{company_name} sector industry market news"

        industry_response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": tavily_api_key,
                "query": industry_query,
                "search_depth": "basic",
                "include_answer": True,
                "include_raw_content": False,
                "max_results": 5,
                "include_domains": ["naver.com", "daum.net", "yonhapnews.co.kr", "einfomax.co.kr", "mk.co.kr",
                                    "sedaily.com"]
            },
            timeout=10
        )

        if industry_response.status_code == 200:
            industry_data = industry_response.json()
            # 검색 결과를 텍스트로 정리
            industry_articles = []
            for result in industry_data.get('results', []):
                industry_articles.append(
                    f"**{result.get('title', 'N/A')}**\n{result.get('content', 'N/A')[:300]}...\n출처: {result.get('url', 'N/A')}")

            news_data['industry_news'] = "\n\n".join(
                industry_articles) if industry_articles else "산업 관련 뉴스를 찾을 수 없습니다."
        else:
            news_data['industry_news'] = "산업 뉴스 검색 실패"

    except Exception as e:
        print(f"Warning: 산업 뉴스 검색 중 오류 발생: {e}")
        news_data['industry_news'] = "산업 뉴스 검색 중 오류 발생"

    return news_data

def _analyze_news_impact(news_data: Dict[str, str], data: Dict[str, str]) -> str:
    """뉴스 분석을 통한 실적 영향 평가"""
    if not news_data.get('company_news') and not news_data.get('industry_news'):
        return "뉴스 데이터가 없어 분석을 수행할 수 없습니다."

    prompt = f"""
    다음 뉴스 정보를 분석하여 기업의 실적과 전망에 미치는 영향을 평가하세요:

    **기업 관련 뉴스:**
    {news_data.get('company_news', '없음')}

    **산업/시장 뉴스:**
    {news_data.get('industry_news', '없음')}

    **기업 기본 정보 (참고용):**
    {data.get('company_business', '없음')[:500]}

    **분석 요청사항:**
    1. 뉴스에서 발견된 주요 이슈들이 기업 실적에 미치는 긍정적/부정적 영향
    2. 시장 및 산업 트렌드가 기업 전망에 주는 시사점
    3. 뉴스 기반 리스크 요인 및 기회 요인 식별
    4. 향후 실적 전망에 반영해야 할 외부 요인들

    **출력 형식:**
    ## 뉴스 기반 시장 분석

    ### 1. 주요 뉴스 이슈 분석
    - **긍정적 요인**: [구체적 설명]
    - **부정적 요인**: [구체적 설명]

    ### 2. 산업 동향 및 시장 환경
    [시장 트렌드와 기업에 미치는 영향]

    ### 3. 리스크 및 기회 요인
    - **기회 요인**: [구체적 설명]
    - **리스크 요인**: [구체적 설명]

    ### 4. 실적 전망에 대한 시사점
    [뉴스 기반 전망 조정 필요성]
    """

    try:
        return news_analysis_agent.run(prompt, temperature=0.2)
    except Exception as e:
        print(f"Warning: 뉴스 분석 중 오류 발생: {e}")
        return "뉴스 분석 중 오류가 발생했습니다."

if __name__ == "__main__":
    # 회사 기본정보 조회
    company_name = company_info['stock_name']
    industry = "직영 중고차 판매 및 매입 플랫폼"

    # Read annual report and summarize
    #comapny_business = read_annual_report(code, out_dir='./data/summary')
    #print(comapny_business.summary)
    #read from md
    with open('./data/summary/company_business.md', 'r', encoding='utf-8') as f:
        company_business = f.read()
    a = 1

    # Read financial data and analyze
    #financial_analysis = analyze_financial_data(fncode, out_dir='./data/summary')
    #print(financial_analysis)

    # Read earnings report
    #earnings_analysis = analyze_earnings(code, out_dir='./data/summary')
    #print(earnings_analysis)

    # Read IR report
    #ir_summary = read_ir_report(fncode, out_dir='./data/summary')
    #print(ir_summary.summary)
    
    # Read and analyze future guidance data
    #future_guidance_analysis = analyze_consensus(fncode, out_dir='./data/summary')
    #print(future_guidance_analysis)

    # Search News from Tavily
    news_analysis = analyze_news(company_name, industry)

    # Process Deep Research with collected data(company_business, financial_analysis, earnings_analysis, ir_summary, future_guidance_analysis)
