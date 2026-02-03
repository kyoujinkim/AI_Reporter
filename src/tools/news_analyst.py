import json
import os
from typing import Dict

import requests
from pydantic import BaseModel

from src.tools.agents import Agent
from src.tools.human_interrupt import HumanEditor


class NewsRelevance(BaseModel):
    """뉴스 관련성 평가 Pydantic 모델"""
    relevance_level: str  # HIGH, MEDIUM, LOW
    reasoning: str  # 평가 근거


class NewsKeywords(BaseModel):
    """뉴스에서 추출된 핵심 키워드 및 추가 탐색 주제 Pydantic 모델"""
    key_trends: list[str]  # 주요 트렌드 키워드 (3-5개)
    emerging_issues: list[str]  # 새로운 이슈들 (2-4개)
    related_companies: list[str]  # 관련 기업들 (2-4개)
    regulatory_topics: list[str]  # 규제/정책 관련 주제 (1-3개)
    technology_keywords: list[str]  # 기술 관련 키워드 (2-4개)
    market_indicators: list[str]  # 시장 지표 관련 (1-3개)
    reasoning: str  # 키워드 선정 근거


class NewsAnalyst:
    def __init__(self, openai_key, tavily_key, model='gpt-4.1-mini'):
        print("\n\n🕵️‍♂️기업뉴스 분석가를 불러옵니다.")
        self.openai_key = openai_key
        self.tavily_key = tavily_key

        self.news_analysis_agent = Agent(
            api_key=openai_key,
            name="NewsAnalysisAgent",
            description="""당신은 뉴스 분석 전문가입니다.
            기업 관련 뉴스와 산업 뉴스를 분석하여 실적 분석에 도움이 되는 인사이트를 도출합니다.
            시장 동향, 경쟁사 현황, 산업 트렌드 등을 파악하여 기업의 실적과 전망에 미치는 영향을 분석합니다.""",
            model=model
        )

        self.news_filter_agent = Agent(
            api_key=openai_key,
            name="NewsFilterAgent",
            description="""당신은 뉴스 관련성 평가 전문가입니다.
            뉴스 기사가 특정 기업이나 산업과 직접적인 관련이 있는지 평가하고 분류합니다.
            기업의 사업 분야, 경쟁사, 공급망, 규제 환경 등을 고려하여 관련성을 판단합니다.""",
            model=model
        )

        self.news_keyword_agent = Agent(
            api_key=openai_key,
            name="NewsKeywordAgent",
            description="""당신은 뉴스 분석 및 키워드 추출 전문가입니다.
            수집된 뉴스를 분석하여 추가 탐색이 필요한 핵심 키워드와 주제를 식별합니다.
            시장 트렌드, 신기술, 규제 변화, 경쟁사 동향 등을 파악하여 심화 검색 방향을 제시합니다.""",
            model=model
        )

        self.human_editor = HumanEditor(openai_key, model)

    def run(self, company_info, company_business: str = None, out_dir=None) -> str:
        code = company_info['stock_code']
        industry = company_info['industry']
        company_name = company_info['corp_name']
        if out_dir is None:
            out_dir = f'./data/A{code}_summary'

        # if news analysis already exists, load and return
        if os.path.exists(f'{out_dir}/news_analysis.md'):
            with open(f'{out_dir}/news_analysis.md', 'r', encoding='utf-8') as md_file:
                return md_file.read()

        if company_business is None:
            with open(f'{out_dir}/company_business.md', 'r', encoding='utf-8') as md_file:
                company_business = md_file.read()

        print(f"뉴스 분석: {company_name} ({code})")
        """뉴스 검색 및 분석 통합 함수"""
        news_data = self._search_news_with_tavily(company_name, industry, company_business)
        analysis = self._analyze_news_impact(news_data, company_business)

        analysis = self.human_editor.run(analysis)

        # Save news analysis to markdown file
        # create out_dir if not exists
        os.makedirs(out_dir, exist_ok=True)
        with open(f'{out_dir}/news_analysis.md', 'w', encoding='utf-8') as md_file:
            md_file.write(analysis)

        return analysis

    def _load_domain_lists(self):
        """외부 설정 파일에서 도메인 목록을 로드하는 함수"""
        try:
            # config 디렉토리의 절대 경로 계산
            current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

            include_domains_path = current_dir + '/data/config/include_domains.json'
            exclude_domains_path = current_dir + '/data/config/exclude_domains.json'

            # include_domains 로드
            with open(include_domains_path, 'r', encoding='utf-8') as f:
                include_domains = json.load(f)

            # exclude_domains 로드
            with open(exclude_domains_path, 'r', encoding='utf-8') as f:
                exclude_domains = json.load(f)

            print(f"도메인 목록 로드 완료: include {len(include_domains)}개, exclude {len(exclude_domains)}개")
            return include_domains, exclude_domains

        except FileNotFoundError as e:
            print(f"Warning: 도메인 설정 파일을 찾을 수 없습니다: {e}")
            # 기본 도메인 목록 반환 (fallback)
            default_include = ["reuters.com", "bloomberg.com", "wsj.com", "ft.com", "cnbc.com"]
            default_exclude = ["reddit.com", "quora.com", "medium.com", "substack.com", "wordpress.com"]
            return default_include, default_exclude
        except json.JSONDecodeError as e:
            print(f"Warning: JSON 파싱 오류: {e}")
            # 기본 도메인 목록 반환 (fallback)
            default_include = ["reuters.com", "bloomberg.com", "wsj.com", "ft.com", "cnbc.com"]
            default_exclude = ["reddit.com", "quora.com", "medium.com", "substack.com", "wordpress.com"]
            return default_include, default_exclude
        except Exception as e:
            print(f"Warning: 도메인 목록 로드 중 예상치 못한 오류: {e}")
            # 기본 도메인 목록 반환 (fallback)
            default_include = ["reuters.com", "bloomberg.com", "wsj.com", "ft.com", "cnbc.com"]
            default_exclude = ["reddit.com", "quora.com", "medium.com", "substack.com", "wordpress.com"]
            return default_include, default_exclude

    def _filter_news_relevance(self, news_articles: list, company_name: str, industry: str, business_summary: str) -> Dict[str, list]:
        """뉴스 기사들의 관련성을 평가하고 분류 (Pydantic 구조화된 응답 사용)"""
        if not news_articles:
            return {"high_relevance": [], "medium_relevance": [], "low_relevance": []}

        # 각 기사별로 관련성 평가
        categorized_news = {"high_relevance": [], "medium_relevance": [], "low_relevance": []}

        for article in news_articles:
            try:
                relevance_prompt = f"""
                다음 뉴스 기사가 지정된 기업 및 산업과 얼마나 관련이 있는지 평가하세요:
    
                **대상 기업**: {company_name}
                **산업 분야**: {industry}
                **사업 요약**: {business_summary[:200]}
    
                **뉴스 기사**:
                {article}
    
                **평가 기준**:
                1. **고관련성 (HIGH)**: 
                   - 해당 기업이 직접 언급되거나 주요 주제
                   - 동일 산업의 핵심 이슈나 트렌드
                   - 해당 기업의 경쟁사 관련 중요 뉴스
                   - 규제 변화나 정책이 해당 산업에 직접 영향
    
                2. **중관련성 (MEDIUM)**:
                   - 관련 산업군이나 인접 분야 이슈
                   - 간접적으로 사업에 영향을 줄 수 있는 경제/시장 동향
                   - 공급망이나 파트너사 관련 뉴스
    
                3. **저관련성 (LOW)**:
                   - 일반적인 경제 뉴스나 다른 산업 이슈
                   - 해당 기업이나 산업과 무관한 내용
    
                relevance_level은 반드시 HIGH, MEDIUM, LOW 중 하나여야 합니다.
                reasoning에는 해당 평가를 내린 구체적인 근거를 설명하세요.
                """

                # Pydantic 구조화된 응답 사용
                relevance_result = self.news_filter_agent.run_with_structured_format(
                    prompt=relevance_prompt,
                    response_format=NewsRelevance,
                    temperature=0.1
                )

                # 응답에서 관련성 레벨 추출
                relevance_level = relevance_result.relevance_level.upper().strip()
                reasoning = relevance_result.reasoning

                # 디버깅용 출력 (선택적)
                print(f"뉴스 평가: {relevance_level} - {reasoning[:100]}...")

                if relevance_level == "HIGH":
                    categorized_news["high_relevance"].append(article)
                elif relevance_level == "MEDIUM":
                    categorized_news["medium_relevance"].append(article)
                elif relevance_level == "LOW":
                    categorized_news["low_relevance"].append(article)
                else:
                    # 예상치 못한 응답인 경우 중관련성으로 분류
                    print(f"Warning: 예상치 못한 관련성 레벨: {relevance_level}")
                    categorized_news["medium_relevance"].append(article)

            except Exception as e:
                print(f"Warning: 뉴스 관련성 평가 중 오류: {e}")
                # 에러 시 중관련성으로 분류
                categorized_news["medium_relevance"].append(article)

        return categorized_news


    def _extract_news_keywords(self, news_articles: list, company_name: str, industry: str,
                               company_business: str) -> NewsKeywords:
        """뉴스에서 핵심 키워드 추출하여 추가 탐색 방향 제시"""
        if not news_articles:
            return NewsKeywords(
                key_trends=[],
                emerging_issues=[],
                related_companies=[],
                regulatory_topics=[],
                technology_keywords=[],
                market_indicators=[],
                reasoning="분석할 뉴스가 없음"
            )

        # 뉴스 내용을 요약하여 키워드 추출용 텍스트 생성
        news_summary = "\n".join(news_articles)

        keyword_prompt = f"""
        다음 뉴스들을 분석하여 추가적인 심화 탐색이 필요한 핵심 키워드들을 추출하세요:
    
        **대상 기업**: {company_name}
        **산업 분야**: {industry}
        **기업 사업**: {company_business[:300]}
    
        **수집된 뉴스들**:
        {news_summary[:2000]}
    
        **키워드 추출 지침**:
    
        1. **주요 트렌드 키워드 (3-5개)**: 
           - 현재 이 산업에서 주목받고 있는 핵심 트렌드
           - 예: "디지털 전환", "ESG 경영", "공급망 다변화" 등
    
        2. **새로운 이슈들 (2-4개)**:
           - 최근 새롭게 부상한 이슈나 변화
           - 예: "새로운 규제", "기술 혁신", "시장 변화" 등
    
        3. **관련 기업들 (2-4개)**:
           - 경쟁사, 파트너사, 공급업체 등
           - 이들의 동향이 대상 기업에 영향을 줄 수 있는 기업들
    
        4. **규제/정책 관련 주제 (1-3개)**:
           - 정부 정책, 규제 변화, 지원책 등
           - 예: "반도체법", "탄소중립", "디지털뉴딜" 등
    
        5. **기술 관련 키워드 (2-4개)**:
           - 신기술, R&D, 특허, 기술 표준 등
           - 예: "AI 반도체", "5G", "자율주행" 등
    
        6. **시장 지표 관련 (1-3개)**:
           - 시장 규모, 성장률, 주요 지표 등
           - 예: "글로벌 시장 점유율", "수출 증가율" 등
    
        각 카테고리별로 구체적이고 검색 가능한 키워드를 제안하세요.
        키워드는 추가 뉴스 검색에 활용될 예정이므로 명확하고 구체적이어야 합니다.
        """

        try:
            keyword_result = self.news_keyword_agent.run_with_structured_format(
                prompt=keyword_prompt,
                response_format=NewsKeywords,
                temperature=0.2
            )

            print(f"키워드 추출 완료: 트렌드 {len(keyword_result.key_trends)}개, "
                  f"이슈 {len(keyword_result.emerging_issues)}개, "
                  f"기업 {len(keyword_result.related_companies)}개")

            return keyword_result

        except Exception as e:
            print(f"Warning: 키워드 추출 중 오류 발생: {e}")
            return NewsKeywords(
                key_trends=[industry],
                emerging_issues=[],
                related_companies=[],
                regulatory_topics=[],
                technology_keywords=[],
                market_indicators=[],
                reasoning="키워드 추출 실패로 기본값 사용"
            )


    def _search_additional_news(self, keywords: NewsKeywords, include_domains: list, exclude_domains: list) -> list:
        """추출된 키워드를 기반으로 추가 뉴스 검색"""
        additional_articles = []

        # 키워드 조합으로 검색 쿼리 생성
        search_queries = []

        # 1. 주요 트렌드 기반 검색
        for trend in keywords.key_trends:
            search_queries.append(f"{trend} korea market analysis 2024")

        # 2. 새로운 이슈 기반 검색
        for issue in keywords.emerging_issues:
            search_queries.append(f"{issue} impact industry outlook")

        # 3. 관련 기업 기반 검색
        for company in keywords.related_companies:
            search_queries.append(f"{company} recent developments business strategy")

        # 4. 규제/정책 기반 검색
        for regulation in keywords.regulatory_topics:
            search_queries.append(f"{regulation} policy impact korea semiconductor")

        # 5. 기술 기반 검색
        for tech in keywords.technology_keywords:
            search_queries.append(f"{tech} technology advancement market trend")

        # 6. 시장 지표 기반 검색
        for indicator in keywords.market_indicators:
            search_queries.append(f"{indicator} korea industry forecast")

        # 쿼리 수 제한 (API 호출 비용 고려)
        search_queries = search_queries[:8]  # 최대 8개 쿼리

        print(f"키워드 기반 추가 검색: {len(search_queries)}개 쿼리 실행")

        for query in search_queries:
            try:
                response = requests.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": self.tavily_key,
                        "query": query,
                        "search_depth": "advanced",
                        "include_answer": False,
                        "include_raw_content": False,
                        "max_results": 5,  # 각 쿼리당 5개씩
                        "days": 90,  # 더 넓은 시간 범위
                        "include_domains": include_domains,
                        "exclude_domains": exclude_domains
                    },
                    timeout=15
                )

                if response.status_code == 200:
                    data = response.json()
                    for result in data.get('results', []):
                        article = f"**{result.get('title', 'N/A')}**\n{result.get('content', 'N/A')[:400]}...\n출처: {result.get('url', 'N/A')}\n검색키워드: {query[:50]}..."
                        additional_articles.append(article)

                # API 호출 간격 조절
                import time
                time.sleep(0.3)

            except Exception as e:
                print(f"Warning: 추가 검색 쿼리 '{query[:30]}...' 실행 중 오류: {e}")
                continue

        return additional_articles


    def _search_news_with_tavily(self, company_name: str, industry: str = "", company_business: str = "") -> Dict[str, str]:
        """Tavily API를 사용한 뉴스 검색 및 관련성 필터링"""
        if not self.tavily_key:
            return {"company_news": "뉴스 검색 불가: Tavily API 키 없음", "industry_news": "뉴스 검색 불가: Tavily API 키 없음"}

        # 외부 파일에서 도메인 목록 로드
        include_domains, exclude_domains = self._load_domain_lists()

        news_data = {}

        # 기업 관련 뉴스 검색
        try:
            company_query = f"{company_name} 실적 earnings recent news"
            company_response = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.tavily_key,
                    "query": company_query,
                    "search_depth": "advanced",
                    "include_answer": False,
                    "include_raw_content": False,
                    "max_results": 15,
                    "days": 60,
                    "include_domains": include_domains,
                    "exclude_domains": exclude_domains
                },
                timeout=15
            )

            if company_response.status_code == 200:
                company_data = company_response.json()
                # 검색 결과를 리스트로 정리
                company_articles = []
                for result in company_data.get('results', []):
                    article = f"**{result.get('title', 'N/A')}**\n{result.get('content', 'N/A')[:300]}...\n출처: {result.get('url', 'N/A')}"
                    company_articles.append(article)

                # 관련성 평가 및 필터링
                if company_articles:
                    filtered_company = self._filter_news_relevance(company_articles, company_name, industry, company_business)

                    # 고관련성과 중관련성 뉴스만 사용
                    relevant_articles = filtered_company["high_relevance"] + filtered_company["medium_relevance"]

                    print(f"기업 뉴스 필터링 결과: 고관련성 {len(filtered_company['high_relevance'])}개, "
                          f"중관련성 {len(filtered_company['medium_relevance'])}개, "
                          f"저관련성 {len(filtered_company['low_relevance'])}개")

                    news_data['company_news'] = "\n\n".join(
                        relevant_articles) if relevant_articles else "관련성 높은 기업 뉴스를 찾을 수 없습니다."
                else:
                    news_data['company_news'] = "기업 관련 뉴스를 찾을 수 없습니다."
            else:
                news_data['company_news'] = "기업 뉴스 검색 실패"

        except Exception as e:
            print(f"Warning: 기업 뉴스 검색 중 오류 발생: {e}")
            news_data['company_news'] = "기업 뉴스 검색 중 오류 발생"

        # 산업 관련 뉴스 검색 - AI 기반 적응형 탐색
        try:
            print("=== 산업 뉴스 적응형 탐색 시작 ===")

            # 1단계: 기본 산업 뉴스 검색
            industry_query = f"{industry} industry trends market outlook recent news korea"
            industry_response = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.tavily_key,
                    "query": industry_query,
                    "search_depth": "advanced",
                    "include_answer": False,
                    "include_raw_content": False,
                    "max_results": 12,
                    "days": 60,
                    "include_domains": include_domains,
                    "exclude_domains": exclude_domains
                },
                timeout=15
            )

            industry_articles = []
            if industry_response.status_code == 200:
                industry_data = industry_response.json()
                for result in industry_data.get('results', []):
                    article = f"**{result.get('title', 'N/A')}**\n{result.get('content', 'N/A')[:350]}...\n출처: {result.get('url', 'N/A')}\n검색단계: 기본검색"
                    industry_articles.append(article)

            print(f"1단계 기본 검색 완료: {len(industry_articles)}개 기사 수집")

            # 2단계: 키워드 추출 및 심화 탐색
            if industry_articles:
                # 수집된 뉴스에서 키워드 추출
                extracted_keywords = self._extract_news_keywords(industry_articles, company_name, industry, company_business)

                print(f"키워드 추출 결과:")
                print(f"- 주요 트렌드: {extracted_keywords.key_trends}")
                print(f"- 새로운 이슈: {extracted_keywords.emerging_issues}")
                print(f"- 관련 기업: {extracted_keywords.related_companies}")
                print(f"- 규제/정책: {extracted_keywords.regulatory_topics}")
                print(f"- 기술 키워드: {extracted_keywords.technology_keywords}")
                print(f"- 시장 지표: {extracted_keywords.market_indicators}")

                # 추출된 키워드로 추가 검색
                additional_articles = self._search_additional_news(extracted_keywords, include_domains, exclude_domains)

                print(f"2단계 키워드 기반 추가 검색 완료: {len(additional_articles)}개 기사 수집")

                # 모든 기사 통합
                all_industry_articles = industry_articles + additional_articles
            else:
                all_industry_articles = []

            # 중복 제거 (제목 기준)
            unique_industry_articles = []
            seen_titles = set()
            for article in all_industry_articles:
                title = article.split('\n')[0]  # 첫 번째 줄이 제목
                if title not in seen_titles:
                    unique_industry_articles.append(article)
                    seen_titles.add(title)

            print(f"중복 제거 후 총 {len(unique_industry_articles)}개 산업 기사")

            # 관련성 평가 및 필터링
            if unique_industry_articles:
                filtered_industry = self._filter_news_relevance(unique_industry_articles, company_name, industry,
                                                           company_business)

                # 고관련성과 중관련성 뉴스만 사용
                relevant_articles = filtered_industry["high_relevance"] + filtered_industry["medium_relevance"]

                print(f"산업 뉴스 필터링 결과: 고관련성 {len(filtered_industry['high_relevance'])}개, "
                      f"중관련성 {len(filtered_industry['medium_relevance'])}개, "
                      f"저관련성 {len(filtered_industry['low_relevance'])}개")

                news_data['industry_news'] = "\n\n".join(
                    relevant_articles) if relevant_articles else "관련성 높은 산업 뉴스를 찾을 수 없습니다."
            else:
                news_data['industry_news'] = "산업 관련 뉴스를 찾을 수 없습니다."

            print("=== 산업 뉴스 적응형 탐색 완료 ===")

        except Exception as e:
            print(f"Warning: 산업 뉴스 검색 중 오류 발생: {e}")
            news_data['industry_news'] = "산업 뉴스 검색 중 오류 발생"

        return news_data


    def _analyze_news_impact(self, news_data: Dict[str, str], company_business: str) -> str:
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
        {company_business[:500]}
    
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
            return self.news_analysis_agent.run(prompt, temperature=0.2)
        except Exception as e:
            print(f"Warning: 뉴스 분석 중 오류 발생: {e}")
            return "뉴스 분석 중 오류가 발생했습니다."