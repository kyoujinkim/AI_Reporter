#!/usr/bin/env python3
"""
AI Reporter - 기업 실적 분석 및 시나리오 생성 시스템

CLAUDE.md에 정의된 요구사항에 따라 다음 기능을 제공:
1. 실적 발표 결과가 기존 예측치를 상회/하회한 이유 분석
2. 향후 실적에 대한 다양한 시나리오 생성 (낙관적, 비관적, 중립적)
3. 각 시나리오에 대한 근거 및 설명 제공
4. 최종 보고서 작성 (마크다운 형식)
5. 차트 생성 (막대, 선, 파이, 산점도 등)
"""

import configparser
import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Union
from pydantic import BaseModel
import matplotlib.pyplot as plt
import pandas as pd
import requests

from src.tools.agents import Agent


class ChartSuggestion(BaseModel):
    """차트 제안 Pydantic 모델"""
    type: str  # bar, line, pie, scatter, area
    title: str
    data_source: str
    description: str
    chart_data: Optional[Dict[str, Union[int, float]]] = {}  # 실제 차트 데이터 (선택적)


class ChartConcept(BaseModel):
    """차트 개념 Pydantic 모델 (데이터 없이 개념만)"""
    type: str  # bar, line, pie, scatter, area
    title: str
    data_source: str
    description: str


class ChartConcepts(BaseModel):
    """차트 개념 목록 Pydantic 모델"""
    charts: List[ChartConcept]


class ChartSuggestions(BaseModel):
    """차트 제안 목록 Pydantic 모델"""
    charts: List[ChartSuggestion]


class AIReporter:
    """AI 기반 기업 실적 분석 및 보고서 생성 시스템"""
    
    def __init__(self, code, config_path: str = "D:/config.ini"):
        """
        Args:
            config_path: OpenAI API 키가 포함된 설정 파일 경로
        """
        self.fncode = 'A'+code
        self.config_path = config_path
        self.data_dir = Path("./data")
        self.summary_dir = self.data_dir / f"{self.fncode}_summary"
        self.output_dir = Path(f"./output/{self.fncode}")
        
        # 디렉터리 생성
        self.output_dir.mkdir(exist_ok=True)
        
        # 설정 로드
        self._load_config()
        
        # AI 에이전트 초기화
        self._initialize_agents()
        
        # 한글 폰트 설정 (차트 생성용)
        self._setup_korean_font()
        
    def _load_config(self):
        """설정 파일에서 API 키 로드"""
        config = configparser.ConfigParser()
        config.read(self.config_path, encoding='utf-8')
        self.api_key = config.get("openai", "API_KEY")
        
    def _initialize_agents(self):
        """AI 에이전트들 초기화"""
        self.analysis_agent = Agent(
            api_key=self.api_key,
            name="AnalysisAgent",
            description="""당신은 기업 실적 분석 전문가입니다. 
            기업의 실적 발표와 기존 예측치를 비교 분석하고, 상회/하회 원인을 심층 분석합니다.
            정확한 데이터 해석과 논리적 분석을 제공하며, 투자자 관점에서 핵심 인사이트를 도출합니다.""",
            model="gpt-4.1-mini"
        )
        
        self.scenario_agent = Agent(
            api_key=self.api_key,
            name="ScenarioAgent", 
            description="""당신은 기업 미래 시나리오 분석 전문가입니다.
            현재 실적과 시장 상황을 바탕으로 낙관적, 중립적, 비관적 시나리오를 생성합니다.
            각 시나리오별로 구체적인 수치와 근거를 제시하며, 실현 가능성을 평가합니다.""",
            model="gpt-4.1-mini"
        )
        
        self.report_agent = Agent(
            api_key=self.api_key,
            name="ReportAgent",
            description="""당신은 투자 보고서 작성 전문가입니다.
            분석 결과를 체계적이고 명확한 마크다운 형식의 보고서로 작성합니다.
            투자자가 이해하기 쉽게 구조화하며, 핵심 포인트를 강조합니다.""",
            model="gpt-4.1-mini"
        )
        
        self.image_selector_agent = Agent(
            api_key=self.api_key,
            name="ImageSelector",
            description="""당신은 보고서에 적합한 이미지를 선택하는 전문가입니다.
            보고서 섹션 내용과 이미지 설명을 비교하여 가장 관련성이 높은 이미지를 선택합니다.
            각 섹션의 주제와 내용에 맞는 최적의 시각 자료를 추천합니다.""",
            model="gpt-4.1-mini"
        )
        
        self.chart_generator_agent = Agent(
            api_key=self.api_key,
            name="ChartGenerator",
            description="""당신은 보고서 데이터 시각화 전문가입니다.
            보고서 내용과 사용된 데이터, 이미지를 분석하여 추가적인 차트가 필요한지 판단합니다.
            투자자에게 유용한 차트 유형과 데이터를 추천하며, 차트별 제목과 설명을 제공합니다.""",
            model="gpt-4.1-mini"
        )
        
    def _setup_korean_font(self):
        """한글 폰트 설정"""
        plt.rcParams['font.family'] = ['Malgun Gothic', 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False
        
    def load_data(self) -> Dict[str, str]:
        """분석에 필요한 데이터 파일들 로드"""
        data = {}
        
        # 필수 데이터 파일들
        required_files = {
            'company_business': self.summary_dir / 'company_business.md',
            'earnings_analysis': self.summary_dir / 'earnings_analysis.md', 
            'financial_analysis': self.summary_dir / 'financial_analysis.md',
            'ir_summary': self.summary_dir / 'ir_summary.md',
            'consensus_analysis': self.summary_dir / 'consensus_analysis.md',
            'news_analysis': self.summary_dir / 'news_analysis.md',
            'estimate_analysis': self.summary_dir / 'estimate_analysis.md',
        }
        
        for key, file_path in required_files.items():
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    data[key] = f.read()
            else:
                print(f"Warning: {file_path} 파일을 찾을 수 없습니다.")
                data[key] = ""
        
        # 이미지 및 설명 데이터 로드
        data['image_descriptions'] = self._load_image_descriptions()
                
        return data
        
    def _load_image_descriptions(self) -> Dict[str, str]:
        """이미지별 설명 파일들 로드"""
        descriptions = {}
        markdown_dir = self.summary_dir / 'ir/markdown'
        
        if markdown_dir.exists():
            for md_file in markdown_dir.glob('*.md'):
                # p002.md -> p002 형태로 키 생성
                key = md_file.stem
                try:
                    with open(md_file, 'r', encoding='utf-8') as f:
                        descriptions[key] = f.read()
                except Exception as e:
                    print(f"Warning: {md_file} 파일 읽기 실패: {e}")
        
        return descriptions
        
    def _select_relevant_images(self, report_section: str, section_title: str, 
                               image_descriptions: Dict[str, str]) -> List[str]:
        """보고서 섹션에 적합한 이미지들 선택"""
        if not image_descriptions:
            return []
            
        # 이미지 설명들을 하나의 텍스트로 결합
        descriptions_text = "\n\n".join([
            f"**{img_id}**: {desc}" 
            for img_id, desc in image_descriptions.items()
        ])
        
        prompt = f"""
        다음 보고서 섹션에 가장 적합한 이미지를 선택하세요:
        
        **보고서 섹션 제목:** {section_title}
        **보고서 섹션 내용:**
        {report_section}
        
        **사용 가능한 이미지들과 설명:**
        {descriptions_text}
        
        **선택 기준:**
        1. 보고서 섹션의 주제와 가장 관련성이 높은 이미지
        2. 섹션 내용을 뒷받침하거나 시각적으로 설명할 수 있는 이미지
        3. 투자자에게 유용한 정보를 제공하는 이미지
        
        **출력 형식:**
        선택된 이미지 ID만 쉼표로 구분하여 나열하세요. (예: p002, p009, p023)
        만약 적합한 이미지가 없다면 "없음"이라고 답하세요.
        """
        
        try:
            response = self.image_selector_agent.run(prompt, temperature=0.1)
            # 응답에서 이미지 ID 추출
            if "없음" in response or "None" in response:
                return []
            
            # 이미지 ID들 추출 및 정리
            image_ids = []
            for img_id in response.replace(" ", "").split(","):
                img_id = img_id.strip()
                if img_id in image_descriptions:
                    image_ids.append(img_id)
                    
            return image_ids[:5]  # 최대 3개까지만
            
        except Exception as e:
            print(f"Warning: 이미지 선택 중 오류 발생: {e}")
            return []
        
    def analyze_earnings_performance(self, data: Dict[str, str]) -> str:
        """실적 발표 결과와 기존 예측치 비교 분석"""
        prompt = f"""
        다음 데이터를 기반으로 실적 발표 결과가 기존 예측치를 상회/하회한 이유를 분석하세요.

        **기업 사업 현황:**
        {data.get('company_business', '데이터 없음')}

        **실적 발표 vs 예측치 비교:**
        {data.get('earnings_analysis', '데이터 없음')}

        **재무제표 분석:**
        {data.get('financial_analysis', '데이터 없음')}

        **IR 발표자료 요약:**
        {data.get('ir_summary', '데이터 없음')}
        
        **뉴스 분석:**
        {data.get('news_analysis', '데이터 없음')}

        **분석 요청사항:**
        1. 실적이 예측치를 상회/하회한 핵심 요인 3가지
        2. 각 요인별 구체적 영향도 (정량적 수치 포함)
        3. 예상치 못한 변수나 일회성 요인 식별
        4. 경영진 가이던스와 실제 결과 차이점 분석
        5. 투자자 관점에서의 시사점

        **출력 형식:**
        ## 실적 서프라이즈 분석

        ### 1. 핵심 요인 분석
        - **요인 1**: [구체적 설명 + 수치]
        - **요인 2**: [구체적 설명 + 수치] 
        - **요인 3**: [구체적 설명 + 수치]

        ### 2. 예상 vs 실제 비교
        [표 형식으로 주요 지표 비교]

        ### 3. 일회성 요인 및 특이사항
        [특별한 변수나 예외적 상황]

        ### 4. 투자 시사점
        [투자자가 알아야 할 핵심 포인트]
        """
        
        return self.analysis_agent.run(prompt, temperature=0.2)
        
    def generate_scenarios(self, data: Dict[str, str], analysis_result: str) -> Dict[str, str]:
        """다음분기 컨센서스 기준 시나리오 생성"""
        scenarios = {}
        
        # 미래 컨센서스 데이터 포함
        consensus_data = data.get('consensus_analysis', '데이터 없음')
        estimation_data = data.get('estimate_analysis', '데이터 없음')

        base_prompt = f"""
        다음 정보를 바탕으로 다음분기 실적에 대한 시나리오를 생성하세요:

        **현재 실적 분석:**
        {analysis_result}

        **애널리스트의 다음분기 컨센서스 분석:**
        {consensus_data}
        
        **AI Agent의 다음분기 컨센서스 분석:**
        {estimation_data}

        **기업 기본 정보:**
        {data.get('company_business', '데이터 없음')}

        **재무 현황:**
        {data.get('financial_analysis', '데이터 없음')}
        
        **IR 발표 요약:**
        {data.get('ir_summary', '데이터 없음')}
        
        **뉴스 분석:**
        {data.get('news_analysis', '데이터 없음')}
        """
        
        # 낙관적 시나리오
        optimistic_prompt = base_prompt + """
        **낙관적 시나리오 (상향 조정) 생성 요청:**
        - 현재 실적 분석 결과를 바탕으로 긍정적 요인들의 임팩트를 평가하여 적절한 상향 조정 폭을 결정하세요
        - 다음분기 컨센서스 수치를 기준으로 분석된 긍정적 요인들이 실현될 경우의 성장 전망
        - 구체적 수치 목표 제시 (매출, 영업이익, 순이익을 분석 근거에 따라 상향 조정)
        - 상향 조정 근거, 조정 폭 결정 이유, 전제 조건 명시
        - 조정 폭에 대해서는 각각의 근거들이 얼마나 기여했는지를 분해하여 설명
        """
        
        # 중립적 시나리오  
        neutral_prompt = base_prompt + """
        **중립적 시나리오 (컨센서스 수준) 생성 요청:**
        - 분석 결과 현재 추세와 시장 상황을 고려하여 컨센서스 달성 가능성을 평가하세요
        - 다음분기 컨센서스 수치 달성을 위한 조건 및 가능성 분석
        - 현재 실적과 트렌드가 지속될 경우의 성장 전망
        - 가장 가능성이 높은 시나리오로서 컨센서스 수치의 타당성 검토
        """
        
        # 비관적 시나리오
        pessimistic_prompt = base_prompt + """
        **비관적 시나리오 (하향 조정) 생성 요청:**
        - 현재 실적 분석에서 식별된 리스크 요인들의 영향도를 평가하여 적절한 하향 조정 폭을 결정하세요
        - 다음분기 컨센서스 대비 부정적 요인들이 현실화될 경우의 성장 전망
        - 하방 리스크를 반영한 구체적 수치 제시 (분석 근거에 기반한 조정)
        - 하향 조정 근거, 조정 폭 결정 이유, 위험 요소 분석
        - 조정 폭에 대해서는 각각의 근거들이 얼마나 기여했는지를 분해하여 설명
        """
        
        scenarios['optimistic'] = self.scenario_agent.run(optimistic_prompt, temperature=0.3)
        scenarios['neutral'] = self.scenario_agent.run(neutral_prompt, temperature=0.3)
        scenarios['pessimistic'] = self.scenario_agent.run(pessimistic_prompt, temperature=0.3)
        
        return scenarios
        
    def make_chart(self, chart_type: str, data: Union[Dict, pd.DataFrame], 
                   title: str, filename: str, **kwargs) -> str:
        """차트 데이터 저장 도구 (CSV 파일만 생성)"""
        # CSV 파일로만 저장하고 차트 위치 정보 반환
        csv_path = self.output_dir / f"{filename}.csv"
        description = f"{chart_type.upper()} 차트"
        
        if isinstance(data, dict):
            chart_data = data
        elif isinstance(data, pd.DataFrame):
            chart_data = data.to_dict('series')
        else:
            chart_data = {}
            
        # CSV 파일 저장
        try:
            with open(csv_path, 'w', newline='', encoding='CP949') as csvfile:
                writer = csv.writer(csvfile)
                
                # 헤더 작성
                writer.writerow(['항목', '값'])
                writer.writerow([])  # 빈 줄
                writer.writerow([f'차트 제목: {title}'])
                writer.writerow([f'차트 유형: {chart_type.upper()}'])
                writer.writerow([f'설명: {description}'])
                writer.writerow([])  # 빈 줄
                writer.writerow(['항목', '값'])  # 데이터 헤더
                
                # 데이터 작성
                for key, value in chart_data.items():
                    writer.writerow([key, value])
                    
            print(f"📊 차트 데이터 CSV 저장: {csv_path}")
            
        except Exception as e:
            print(f"Warning: CSV 저장 중 오류 발생: {e}")
        
        # 차트 위치 정보 반환 (실제 이미지 대신)
        return f"[차트 위치] {title} ({chart_type.upper()}) - 데이터: {csv_path}"
        
    def _generate_charts_from_report(self, report_content: str, data: Dict[str, str], 
                                    image_descriptions: Dict[str, str]) -> List[str]:
        """보고서 내용과 데이터를 기반으로 차트들 생성"""
        # 차트 생성 제안 요청
        chart_suggestions = self._get_chart_suggestions(report_content, data, image_descriptions)
        
        if not chart_suggestions:
            return []
            
        generated_charts = []
        
        for suggestion in chart_suggestions:
            try:
                chart_path = self._create_chart_from_suggestion(suggestion, data)
                if chart_path:
                    generated_charts.append(chart_path)
            except Exception as e:
                print(f"Warning: 차트 생성 중 오류 발생: {e}")
                continue
                
        return generated_charts
        
    def _get_chart_suggestions(self, report_content: str, data: Dict[str, str], 
                              image_descriptions: Dict[str, str]) -> List[ChartSuggestion]:
        """보고서 내용을 바탕으로 차트 생성 제안 받기 (2단계 프로세스)"""
        
        # 1단계: 차트 개념 제안
        chart_concepts = self._get_chart_concepts(report_content, data, image_descriptions)
        
        if not chart_concepts:
            return []
        
        # 2단계: 각 개념에 대해 실제 데이터 생성
        chart_suggestions = []
        for concept in chart_concepts:
            try:
                suggestion = self._generate_chart_data_for_concept(concept, data)
                if suggestion:
                    chart_suggestions.append(suggestion)
            except Exception as e:
                print(f"Warning: 차트 데이터 생성 중 오류 발생: {e}")
                continue
                
        return chart_suggestions[:3]  # 최대 3개
        
    def _get_chart_concepts(self, report_content: str, data: Dict[str, str], 
                           image_descriptions: Dict[str, str]) -> List[ChartConcept]:
        """1단계: 차트 개념만 제안 (데이터 없이)"""
        
        # 이미지 설명들을 요약
        image_summary = "\n".join([
            f"- {img_id}: {desc.split('## 1) 핵심 요약')[1].split('## 2)')[0] if '## 1) 핵심 요약' in desc else desc[:200]}" 
            for img_id, desc in image_descriptions.items()
        ])
        
        prompt = f"""
        다음 보고서와 원본 데이터를 분석하여 투자자에게 유용한 차트 개념들을 제안하세요.
        이 단계에서는 실제 데이터는 생성하지 말고, 어떤 차트가 필요한지만 결정하세요.
        
        **생성된 보고서 내용:**
        {report_content[:3000]}...
        
        **원본 데이터 요약:**
        - 기업 사업 현황: {len(data.get('company_business', ''))}자
        - 실적 분석: {len(data.get('earnings_analysis', ''))}자
        - 재무 분석: {len(data.get('financial_analysis', ''))}자
        - IR 요약: {len(data.get('ir_summary', ''))}자
        - 컨센서스 분석: {len(data.get('consensus_analysis', ''))}자
        
        **이미지 설명:**
        {image_summary}
        
        **차트 개념 제안 지침:**
        1. 투자자 의사결정에 가장 도움되는 차트 우선
        2. 시나리오 비교, 실적 추이, 예측 vs 실제 등 핵심 차트 중심
        3. 차트 타입은 데이터 성격에 맞게 선택 (bar: 비교, line: 추이, pie: 구성비)
        4. 최대 3개의 차트만 제안
        
        텍스트에서 의미 있는 차트를 만들 수 있는 정보가 부족하다면 빈 배열을 반환하세요.
        """
        
        try:
            response = self.chart_generator_agent.run_with_structured_format(
                prompt=prompt,
                response_format=ChartConcepts,
                temperature=0.3
            )
            
            if hasattr(response, 'charts'):
                return response.charts[:5]  # 최대 3개
            else:
                return []

        except Exception as e:
            print(f"Warning: 차트 개념 제안 중 오류 발생: {e}")
            return []
            
    def _generate_chart_data_for_concept(self, concept: ChartConcept, 
                                       data: Dict[str, str]) -> Optional[ChartSuggestion]:
        """2단계: 특정 차트 개념에 대한 실제 데이터 생성"""
        
        # 데이터 소스 기반으로 필요한 데이터만 선택
        relevant_data = self._select_relevant_data_for_chart(concept.data_source, data)
        
        prompt = f"""
        다음 차트 개념에 대해 제공된 관련 데이터에서 실제 수치를 추출하여 차트 데이터를 생성하세요:
        
        **차트 개념:**
        - 유형: {concept.type}
        - 제목: {concept.title}
        - 데이터 소스: {concept.data_source}
        - 설명: {concept.description}
        
        **관련 데이터:**
        {relevant_data}
        
        **데이터 생성 요구사항:**
        1. 위 텍스트에서 언급된 구체적 수치를 찾아서 chart_data로 변환
        2. 누락된 수치는 문맥상 합리적으로 추론하여 보완
        3. chart_data는 {{key: value}} 형태의 딕셔너리
        4. 모든 값은 숫자(int 또는 float)여야 함
        5. 차트 유형에 맞는 적절한 데이터 구조 생성
        
        적절한 데이터를 찾을 수 없다면 chart_data를 빈 딕셔너리로 설정하세요.
        """
        
        try:
            response = self.chart_generator_agent.run_with_structured_format(
                prompt=prompt,
                response_format=ChartSuggestion,
                temperature=0.1
            )
            
            # 응답이 ChartSuggestion 객체이고 chart_data가 있는 경우만 반환
            if hasattr(response, 'chart_data') and response.chart_data:
                return response
            else:
                return None

        except Exception as e:
            print(f"Warning: {concept.title} 차트 데이터 생성 중 오류: {e}")
            return None
            
    def _select_relevant_data_for_chart(self, data_source: str, data: Dict[str, str]) -> str:
        """데이터 소스 기반으로 필요한 원본 데이터만 선택"""
        relevant_data_parts = []
        data_source_lower = data_source.lower()
        
        # 데이터 소스 키워드 기반 매핑
        data_mapping = {
            'company_business': ['사업', '비즈니스', 'business', '회사', '기업'],
            'earnings_analysis': ['실적', '실적분석', 'earnings', '수익', '매출', '이익'],
            'financial_analysis': ['재무', '재무제표', 'financial', '자산', '부채', '현금'],
            'ir_summary': ['ir', 'investor', 'relations', '투자자', '발표'],
            'consensus_analysis': ['컨센서스', 'consensus', '전망', '예측', '목표']
        }
        
        # 시나리오 관련 데이터는 컨센서스와 실적 모두 필요
        if any(keyword in data_source_lower for keyword in ['시나리오', 'scenario', '전망', '예측']):
            relevant_data_parts.append(f"**컨센서스 분석:**\n{data.get('consensus_analysis', '데이터 없음')}")
            relevant_data_parts.append(f"**실적 분석:**\n{data.get('earnings_analysis', '데이터 없음')}")
        
        # 추이/트렌드 관련 데이터는 재무와 실적 모두 필요
        elif any(keyword in data_source_lower for keyword in ['추이', 'trend', '성장', 'growth', '변화']):
            relevant_data_parts.append(f"**재무 분석:**\n{data.get('financial_analysis', '데이터 없음')}")
            relevant_data_parts.append(f"**실적 분석:**\n{data.get('earnings_analysis', '데이터 없음')}")
        
        # 비교 관련 데이터는 실적과 컨센서스 필요
        elif any(keyword in data_source_lower for keyword in ['비교', 'vs', '예상', '실제']):
            relevant_data_parts.append(f"**실적 분석:**\n{data.get('earnings_analysis', '데이터 없음')}")
            relevant_data_parts.append(f"**컨센서스 분석:**\n{data.get('consensus_analysis', '데이터 없음')}")
        
        # 그 외의 경우 키워드 매칭으로 데이터 선택
        else:
            for data_key, keywords in data_mapping.items():
                if any(keyword in data_source_lower for keyword in keywords):
                    data_title = data_key.replace('_', ' ').title()
                    relevant_data_parts.append(f"**{data_title}:**\n{data.get(data_key, '데이터 없음')}")
        
        # 매칭되는 데이터가 없으면 실적 분석을 기본으로 사용
        if not relevant_data_parts:
            relevant_data_parts.append(f"**실적 분석:**\n{data.get('earnings_analysis', '데이터 없음')}")
        
        return "\n\n".join(relevant_data_parts)
            
            
    def _save_chart_data_to_csv(self, chart_data: Dict[str, Union[int, float]], 
                                title: str, description: str) -> str:
        """차트 데이터를 CSV 파일로 저장"""
        # 파일명 생성 (한글 제거)
        import re
        filename = re.sub(r'[^a-zA-Z0-9_]', '_', title.lower())[:20]
        csv_path = self.output_dir / f"chart_data_{filename}.csv"
        
        try:
            with open(csv_path, 'w', newline='', encoding='CP949') as csvfile:
                writer = csv.writer(csvfile)
                
                # 헤더 작성
                writer.writerow(['항목', '값'])
                writer.writerow([])  # 빈 줄
                writer.writerow([f'차트 제목: {title}'])
                writer.writerow([f'설명: {description}'])
                writer.writerow([])  # 빈 줄
                writer.writerow(['항목', '값'])  # 데이터 헤더
                
                # 데이터 작성
                for key, value in chart_data.items():
                    writer.writerow([key, value])
                    
            print(f"📊 차트 데이터 CSV 저장: {csv_path}")
            return str(csv_path)
            
        except Exception as e:
            print(f"Warning: CSV 저장 중 오류 발생: {e}")
            return ""

    def _create_chart_from_suggestion(self, suggestion: ChartSuggestion, data: Dict[str, str]) -> Optional[str]:
        """제안된 차트 생성 (Pydantic 모델에서 직접 데이터 사용)"""
        chart_type = suggestion.type
        title = suggestion.title
        chart_data = suggestion.chart_data  # Pydantic 모델에서 직접 가져옴
        
        if not chart_data:
            return None
            
        # 파일명 생성 (한글 제거)
        import re
        filename = re.sub(r'[^a-zA-Z0-9가-힣_]', '_', title.lower())[:20]
        
        # CSV 파일로 차트 데이터 저장
        #self._save_chart_data_to_csv(chart_data, title, suggestion.description)
        return self.make_chart(
            chart_type=chart_type,
            data=chart_data,
            title=title,
            filename=f"generated_{filename}"
        )
        
        
    def generate_report(self, analysis_result: str, scenarios: Dict[str, str], 
                       charts: List[str] = None, data: Dict[str, str] = None,
                        ) -> str:
        """최종 보고서 생성 (이미지 및 뉴스 분석 포함)"""

        report_prompt = f"""
        다음 분석 결과를 바탕으로 투자자를 위한 종합 보고서를 마크다운 형식으로 작성하세요:

        **실적 분석 결과:**
        {analysis_result}

        **시나리오 분석:**
        **낙관적 시나리오:**
        {scenarios.get('optimistic', '')}

        **중립적 시나리오:**
        {scenarios.get('neutral', '')}

        **비관적 시나리오:**
        {scenarios.get('pessimistic', '')}

        **보고서 구성 요구사항:**
        1. 제목: 회사명 + 실적 분석 리포트 + 날짜
        2. 요약 (Executive Summary)
        3. 실적 분석 상세
        4. 시장 및 뉴스 동향 분석
        5. 다음분기 시나리오별 분석 (표 형식과 해설 문단 포함)
        - 주의사항: 실적 추정치는 낙관적 > 중립적 > 비관적 순이어야 함
        6. 리스크 요인
        7. 결론

        **출력 형식:** 완전한 마크다운 문서
        """
        
        report_content = self.report_agent.run(report_prompt, temperature=0.2)
        
        # 이미지 통합
        if data and 'image_descriptions' in data:
            report_content = self._integrate_images_into_report(
                report_content, data['image_descriptions']
            )
        
        # 차트가 있다면 보고서에 추가 (위치 정보만)
        if charts:
            chart_section = "\n\n## 차트 분석\n\n"
            for i, chart_info in enumerate(charts, 1):
                chart_section += f"### 차트 {i}\n{chart_info}\n\n"
            report_content += chart_section
            
        return report_content
        
    def _integrate_images_into_report(self, report_content: str, 
                                     image_descriptions: Dict[str, str]) -> str:
        """보고서 결론 섹션에만 관련 이미지들 통합"""
        if not image_descriptions:
            return report_content
            
        # 보고서를 섹션별로 분할
        sections = report_content.split('\n## ')
        integrated_content = sections[0]  # 제목 부분
        
        for i, section in enumerate(sections[1:], 1):
            section_lines = section.split('\n')
            section_title = section_lines[0] if section_lines else f"섹션 {i}"
            section_text = '\n'.join(section_lines)
            
            # 섹션 추가
            integrated_content += f"\n## {section_text}"
            
            # 마지막 섹션(결론)에만 이미지 추가
            is_conclusion = any(keyword in section_title.lower() for keyword in 
                              ['결론', 'conclusion', '마무리', '종합'])
            
            if is_conclusion or i == len(sections) - 1:  # 결론 섹션이거나 마지막 섹션인 경우
                # 전체 보고서 내용을 기준으로 이미지 선택
                full_report_text = report_content
                # 간혹 이미지가 선택되지 않는 경우를 대비해 최대 2회 시도
                counter = 0
                while counter < 2:
                    relevant_images = self._select_relevant_images(
                        full_report_text, "종합 분석", image_descriptions
                    )
                    if relevant_images:
                        break
                    else:
                        print("Warning: 관련 이미지가 선택되지 않아 재시도 중...")
                        counter += 1
                
                # 관련 이미지가 있으면 섹션 끝에 추가
                if relevant_images:
                    integrated_content += "\n\n### 참고 자료\n\n"
                    for img_id in relevant_images:
                        img_path = f"./src/data/{self.fncode}_summary/ir/images/{img_id}.png"
                        integrated_content += f"![{img_id}]({img_path})\n\n"
                        # 이미지 설명도 간단히 추가
                        desc_lines = image_descriptions[img_id].split('\n')
                        title_line = next((line for line in desc_lines if '핵심 요약' in line), None)
                        if title_line:
                            idx = desc_lines.index(title_line)
                            if idx + 1 < len(desc_lines):
                                integrated_content += f"*{desc_lines[idx + 1].strip()}*\n\n"
        
        return integrated_content
        
    def save_report(self, report_content: str, filename: str = None) -> str:
        """보고서를 파일로 저장"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"ai_report_{self.fncode}_{timestamp}.md"
            
        report_path = self.output_dir / filename
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_content)
            
        return str(report_path)
        
    def run_full_analysis(self) -> str:
        """전체 분석 프로세스 실행"""
        print("\n🚀 AI Reporter 시작...")
        
        # 1. 데이터 로드
        print("\n📊 데이터 로딩...")
        data = self.load_data()

        # 2. 실적 분석
        print("\n🔍 실적 성과 분석...")
        analysis_result = self.analyze_earnings_performance(data)
        
        # 3. 시나리오 생성
        print("\n🎯 시나리오 생성...")
        scenarios = self.generate_scenarios(data, analysis_result)
        
        # 4. 최종 보고서 생성 (뉴스 분석 포함)
        print("\n📝 보고서 생성...")
        report = self.generate_report(analysis_result, scenarios, None, data)
        
        # 5. 보고서 기반 차트 생성
        print("\n📈 보고서 기반 차트 생성...")
        charts = self._generate_charts_from_report(
            report, data, data.get('image_descriptions', {})
        )
        
        # 6. 차트가 생성되었다면 보고서에 추가 (위치 정보만)
        if charts:
            print(f"\n✅ {len(charts)}개의 차트가 생성되었습니다.")
            chart_section = "\n\n## 추가 차트 분석\n\n"
            for i, chart_info in enumerate(charts, 1):
                chart_section += f"### 차트 {i}\n{chart_info}\n\n"
            report += chart_section
        
        # 7. 최종 보고서 저장
        report_path = self.save_report(report)
        
        print(f"\n✅ 분석 완료! 보고서 저장: {report_path}")
        
        return report_path


    def run(self):
        """메인 실행 함수"""
        try:
            report_path = self.run_full_analysis()

            print(f"\n🎉 AI Reporter 분석이 완료되었습니다!")
            print(f"📄 보고서 경로: {report_path}")

            # 보고서 내용 미리보기
            with open(report_path, 'r', encoding='utf-8') as f:
                content = f.read()
                print("\n" + "="*50)
                print("보고서 미리보기 (처음 500자)")
                print("="*50)
                print(content[:500] + "...")

        except Exception as e:
            print(f"❌ 오류 발생: {e}")
            raise


if __name__ == "__main__":
    reporter = AIReporter("095340")
    reporter.run()