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

import os
import json
import configparser
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import seaborn as sns
import pandas as pd

from src.tools.agents import Agent


class AIReporter:
    """AI 기반 기업 실적 분석 및 보고서 생성 시스템"""
    
    def __init__(self, config_path: str = "D:/config.ini"):
        """
        Args:
            config_path: OpenAI API 키가 포함된 설정 파일 경로
        """
        self.config_path = config_path
        self.data_dir = Path("./data")
        self.summary_dir = self.data_dir / "summary"
        self.output_dir = Path("./output")
        
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
            'consensus_analysis': self.summary_dir / 'consensus_analysis.md'
        }
        
        for key, file_path in required_files.items():
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    data[key] = f.read()
            else:
                print(f"Warning: {file_path} 파일을 찾을 수 없습니다.")
                data[key] = ""
                
        return data
        
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
        
        base_prompt = f"""
        다음 정보를 바탕으로 다음분기 실적에 대한 시나리오를 생성하세요:

        **현재 실적 분석:**
        {analysis_result}

        **다음분기 컨센서스 분석:**
        {consensus_data}

        **기업 기본 정보:**
        {data.get('company_business', '데이터 없음')}

        **재무 현황:**
        {data.get('financial_analysis', '데이터 없음')}
        """
        
        # 낙관적 시나리오
        optimistic_prompt = base_prompt + """
        **낙관적 시나리오 (상향 조정) 생성 요청:**
        - 현재 실적 분석 결과를 바탕으로 긍정적 요인들의 임팩트를 평가하여 적절한 상향 조정 폭을 결정하세요
        - 다음분기 컨센서스 수치를 기준으로 분석된 긍정적 요인들이 실현될 경우의 성장 전망
        - 구체적 수치 목표 제시 (매출, 영업이익, 순이익을 분석 근거에 따라 상향 조정)
        - 상향 조정 근거, 조정 폭 결정 이유, 전제 조건 명시
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
        """
        
        scenarios['optimistic'] = self.scenario_agent.run(optimistic_prompt, temperature=0.3)
        scenarios['neutral'] = self.scenario_agent.run(neutral_prompt, temperature=0.2) 
        scenarios['pessimistic'] = self.scenario_agent.run(pessimistic_prompt, temperature=0.3)
        
        return scenarios
        
    def make_chart(self, chart_type: str, data: Union[Dict, pd.DataFrame], 
                   title: str, filename: str, **kwargs) -> str:
        """차트 생성 도구"""
        plt.figure(figsize=kwargs.get('figsize', (12, 8)))
        
        if chart_type == 'bar':
            if isinstance(data, dict):
                plt.bar(data.keys(), data.values())
            elif isinstance(data, pd.DataFrame):
                data.plot(kind='bar')
                
        elif chart_type == 'line':
            if isinstance(data, dict):
                plt.plot(list(data.keys()), list(data.values()))
            elif isinstance(data, pd.DataFrame):
                data.plot(kind='line')
                
        elif chart_type == 'pie':
            if isinstance(data, dict):
                plt.pie(data.values(), labels=data.keys(), autopct='%1.1f%%')
            elif isinstance(data, pd.DataFrame):
                plt.pie(data.iloc[:, 0], labels=data.index, autopct='%1.1f%%')
                
        elif chart_type == 'scatter':
            if isinstance(data, pd.DataFrame) and len(data.columns) >= 2:
                plt.scatter(data.iloc[:, 0], data.iloc[:, 1])
                
        elif chart_type == 'area':
            if isinstance(data, dict):
                plt.fill_between(data.keys(), data.values(), alpha=0.3)
                plt.plot(data.keys(), data.values())
            elif isinstance(data, pd.DataFrame):
                data.plot(kind='area', alpha=0.3)
        
        plt.title(title, fontsize=16)
        plt.tight_layout()
        
        chart_path = self.output_dir / f"{filename}.png"
        plt.savefig(chart_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        return str(chart_path)
        
    def generate_report(self, analysis_result: str, scenarios: Dict[str, str], 
                       charts: List[str] = None) -> str:
        """최종 보고서 생성"""
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
        4. 다음분기 시나리오별 분석 (표 형식 포함)
        5. 리스크 요인
        6. 결론

        **출력 형식:** 완전한 마크다운 문서
        """
        
        report_content = self.report_agent.run(report_prompt, temperature=0.2)
        
        # 차트가 있다면 보고서에 추가
        if charts:
            chart_section = "\n\n## 차트 분석\n\n"
            for i, chart_path in enumerate(charts, 1):
                chart_section += f"![차트 {i}]({chart_path})\n\n"
            report_content += chart_section
            
        return report_content
        
    def save_report(self, report_content: str, filename: str = None) -> str:
        """보고서를 파일로 저장"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"ai_report_{timestamp}.md"
            
        report_path = self.output_dir / filename
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_content)
            
        return str(report_path)
        
    def run_full_analysis(self) -> str:
        """전체 분석 프로세스 실행"""
        print("🚀 AI Reporter 시작...")
        
        # 1. 데이터 로드
        print("📊 데이터 로딩...")
        data = self.load_data()
        
        # 2. 실적 분석
        print("🔍 실적 성과 분석...")
        analysis_result = self.analyze_earnings_performance(data)
        
        # 3. 시나리오 생성
        print("🎯 시나리오 생성...")
        scenarios = self.generate_scenarios(data, analysis_result)
        
        # 4. 차트 생성 (예시)
        print("📈 차트 생성...")
        charts = []
        
        # 예시 차트 데이터 (실제로는 데이터에서 추출)
        sample_data = {
            '1Q': 100, '2Q': 120, '3Q': 115, '4Q': 130
        }
        
        chart_path = self.make_chart(
            chart_type='bar',
            data=sample_data,
            title='분기별 실적 추이',
            filename='quarterly_performance'
        )
        charts.append(chart_path)
        
        # 5. 최종 보고서 생성
        print("📝 보고서 생성...")
        report = self.generate_report(analysis_result, scenarios, charts)
        
        # 6. 보고서 저장
        report_path = self.save_report(report)
        
        print(f"✅ 분석 완료! 보고서 저장: {report_path}")
        
        return report_path


def main():
    """메인 실행 함수"""
    try:
        reporter = AIReporter()
        report_path = reporter.run_full_analysis()
        
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
    main()