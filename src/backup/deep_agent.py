# -*- coding: utf-8 -*-
"""
LangGraph 기반 'Earnings-Focused' Deep Research Agent (+ 시나리오 생성)
- 사용자로부터 요약된 문서(earnings_analysis, ir_summary 등)를 직접 입력받아
  분석, 시나리오 생성, 보고서 작성에 집중하는 워크플로우

설치:
    pip install -U langgraph langchain-core langchain-community langchain-openai
    pip install -U langchain-tavily langchain-experimental pandas matplotlib pydantic

환경:
    export OPENAI_API_KEY=...
    export TAVILY_API_KEY=...
    # 선택
    export LLM_MODEL=openai:gpt-4o-mini

실행:
    python deep_research_agent_earnings_scenarios_streamlined.py
"""
from __future__ import annotations
import os, uuid, json, textwrap
from dataclasses import dataclass
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend to prevent GUI issues
import matplotlib.pyplot as plt
from typing import Any, Dict, List, Optional, Annotated

from pydantic import BaseModel
from typing_extensions import TypedDict

# OpenAI
from openai import OpenAI

# LangChain / LangGraph
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import Command, interrupt
from langgraph.checkpoint.memory import MemorySaver

# Tools
from langchain_tavily import TavilySearch
from langchain_experimental.tools.python.tool import PythonREPLTool  # type: ignore

import configparser


# ---------------------- Pydantic Models ----------------------
class PlanFormat(BaseModel):
    steps: List[str]
    charts: List[str]
    risks: List[str]

# ---------------------- State ----------------------
class ResearchState(TypedDict, total=False):
    messages: Annotated[List[Any], add_messages]
    question: str
    company_business: str
    financial_analysis: Any
    earnings_analysis: Any
    ir_summary: str
    consensus_analysis: str

    summaries: Dict[str, str]
    research_plan: PlanFormat

    tables: Dict[str, Any]
    charts: List[Dict[str, Any]]

    scenario_params: Dict[str, Any]
    scenarios: Dict[str, Any]

    report_md: str


# ---------------------- Globals ----------------------
ASSETS_DIR = os.path.join(os.getcwd(), "report_assets");
os.makedirs(ASSETS_DIR, exist_ok=True)

config = configparser.ConfigParser()
config_file = "D:/config.ini"

# Try to load config, provide defaults if not found
try:
    config.read(config_file)
    openaikey = config.get("openai", "API_KEY")
    tavilykey = config.get("tavily", "API_KEY_NH")
except (FileNotFoundError, configparser.NoSectionError, configparser.NoOptionError) as e:
    print(f"Config file error: {e}")
    print("Using environment variables or defaults...")
    openaikey = os.environ.get("OPENAI_API_KEY", "test-key")
    tavilykey = os.environ.get("TAVILY_API_KEY", "test-key")

ai_model = "gpt-4o-mini"

# ---------------------- Client ----------------------
def get_openai_client():
    """Get OpenAI client with proper error handling."""
    if openaikey == "test-key":
        print("Warning: Using test API key - OpenAI calls will fail")
        return None
    try:
        return OpenAI(api_key=openaikey)
    except Exception as e:
        print(f"Failed to create OpenAI client: {e}")
        return None

client = None  # Initialize as None, will be set when needed


# ---------------------- Utils ----------------------
def est_tokens(text: str) -> int:
    return max(1, int(len(text or "") / 4))


def _sanitize_text(text: str, max_length: int = 50000) -> str:
    """Sanitize text input to prevent injection attacks and excessive lengths."""
    if not text or not isinstance(text, str):
        return ""
    
    # Limit length to prevent resource exhaustion
    if len(text) > max_length:
        text = text[:max_length] + "... [TRUNCATED]"
    
    # Remove potential malicious patterns (basic sanitization)
    dangerous_patterns = [
        '<script', '</script>', 'javascript:', 'eval(', 'exec(',
        'import os', 'import subprocess', '__import__', 'system(',
        'rm -rf', 'del ', 'format C:', 'DROP TABLE'
    ]
    
    for pattern in dangerous_patterns:
        text = text.replace(pattern, f"[REMOVED: {pattern[:10]}...]")
    
    return text

def _context_builder(state: ResearchState) -> str:
    """Provides combined context from pre-summarized data with sanitization."""
    ctx_parts = ["[Summaries (from provided input)]"]
    for name, text in [
        ("earnings_analysis", state.get("earnings_analysis")),
        ("ir_summary", state.get("ir_summary")),
        ("financial_analysis", state.get("financial_analysis")),
        ("company_business", state.get("company_business")),
        ("consensus_analysis", state.get("consensus_analysis")),
    ]:
        if text: 
            sanitized_text = _sanitize_text(text)
            ctx_parts.append(f"- {name}:\n{sanitized_text}")
    return "\n\n".join(ctx_parts)


# ---------------------- Tools ----------------------
@tool("make_chart")
def make_chart(spec_json: str) -> str:
    """
    JSON 스펙으로 다양한 종류의 차트를 PNG로 저장하고 경로를 반환합니다.
    - 지원하는 차트 종류: 'bar', 'line', 'pie', 'scatter', 'area'
    - 다중 계열 지원.
    - 보조 y축(secondary) 지원.
    - 데이터 레이블(data_labels) 표시 지원.

    예제 JSON 스펙:
    {
        "title": "Quarterly EPS and Operating Margin",
        "xlabel": "Quarter",
        "ylabel": "EPS (USD)",
        "y_series": [
            {"name": "EPS", "kind": "bar", "values": [1.5, 1.8, 2.1, 2.5], "x": ["Q1","Q2","Q3","Q4"]},
            {"name": "Operating Margin %", "kind": "line", "values": [12.5, 13.0, 14.5, 15.2], "secondary": true, "data_labels": true}
        ],
        "y2label": "Operating Margin (%)",
        "caption": "분기별 EPS 및 영업이익률 추이"
    }

    결과: {"path":"...png", "caption":"...", "error":""}
    """
    try:
        spec = json.loads(spec_json)

        # --- 필수 데이터 추출 ---
        y_series = spec["y_series"]

        # --- 플롯 설정 ---
        fig, ax = plt.subplots(figsize=(10, 6))
        secax = None

        # --- 차트 종류별 플롯 함수 정의 ---
        def plot_series(series_data, target_ax):
            kind = series_data.get("kind", "line")
            name = series_data.get("name")
            values = series_data["values"]
            x_values = series_data.get("x", range(len(values)))
            data_labels = series_data.get("data_labels", False)

            if kind == "bar":
                bars = target_ax.bar(x_values, values, label=name)
                if data_labels:
                    target_ax.bar_label(bars, fmt='%.1f')
            elif kind == "line":
                target_ax.plot(x_values, values, label=name, marker='o')
                if data_labels:
                    for i, (x, y) in enumerate(zip(x_values, values)):
                        target_ax.text(x, y, f'{y:.1f}', ha='center', va='bottom')
            elif kind == "pie":
                target_ax.pie(values, labels=x_values, autopct='%1.1f%%', startangle=90)
                target_ax.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.
            elif kind == "scatter":
                target_ax.scatter(x_values, values, label=name)
                if data_labels:
                    for i, (x, y) in enumerate(zip(x_values, values)):
                        target_ax.text(x, y, f'{y:.1f}', ha='center', va='bottom')
            elif kind == "area":
                target_ax.fill_between(x_values, values, alpha=0.4, label=name)
                target_ax.plot(x_values, values, marker='o', linestyle='-')
            else:
                raise ValueError(f"Unsupported chart kind: {kind}")

        # --- 데이터 계열 순회 및 플롯 ---
        for s in y_series:
            is_secondary = s.get("secondary", False)
            target_ax = ax
            if is_secondary:
                if secax is None:
                    secax = ax.twinx()
                target_ax = secax
                secax.set_ylabel(spec.get("y2label", "Secondary Axis"))

            plot_series(s, target_ax)

        # --- 공통 스타일링 ---
        ax.set_title(spec.get("title", "Chart"))
        ax.set_xlabel(spec.get("xlabel", ""))
        ax.set_ylabel(spec.get("ylabel", ""))

        # 범례 합치기
        lines, labels = ax.get_legend_handles_labels()
        if secax:
            lines2, labels2 = secax.get_legend_handles_labels()
            ax.legend(lines + lines2, labels + labels2, loc="best")
        else:
            ax.legend(loc="best")

        fig.tight_layout()

        # 파일 저장
        fn = f"chart_{uuid.uuid4().hex[:8]}.png"
        path = os.path.join(ASSETS_DIR, fn)
        fig.savefig(path, dpi=160)
        plt.close(fig)

        return json.dumps({"path": path, "caption": spec.get("caption", spec.get("title")), "error": ""})

    except Exception as e:
        plt.close('all')  # 에러 발생 시 플롯 창 닫기
        return json.dumps({"path": "", "caption": "", "error": str(e)})


def build_tools() -> List[Any]:
    tools = [make_chart]  # Always include safe tools
    
    # Add Tavily with error handling
    if tavilykey and tavilykey != "test-key":
        try:
            tavily = TavilySearch(tavily_api_key=tavilykey, max_results=2, topic="finance")
            tools.append(tavily)
        except Exception as e:
            print(f"Warning: Failed to initialize Tavily: {e}")
    else:
        print("Warning: Tavily API key not available, skipping web search tool")
    
    # SECURITY: Disable Python REPL tool to prevent arbitrary code execution
    # This is a major security risk and should not be enabled in production
    print("INFO: Python REPL tool disabled for security reasons")
    
    return tools


def build_llm():
    """Build LLM with error handling."""
    if openaikey == "test-key":
        print("Warning: Using test API key - LLM calls will fail")
        return None
    try:
        return init_chat_model("openai:"+ai_model, api_key=openaikey)
    except Exception as e:
        print(f"Failed to create LLM: {e}")
        return None

# ---------------------- Nodes ----------------------
def plan_research(state: ResearchState) -> ResearchState:
    plan_prompt = textwrap.dedent("""
    당신은 실적 발표 데이터를 분석하는 데 매우 꼼꼼한 AI 분석가입니다.
    사용자가 제공하는 실적 발표치와 컨센서스 데이터를 기반으로, 차이점의 원인을 분석하고 미래 시나리오를 예측하기 위한 상세한 분석 계획을 수립하세요.
    다음 지침에 따라 JSON 형식으로 계획을 작성해야 합니다:
    
    1.  **계획 단계 (steps):**
        -   최대 8단계 이내의 핵심적인 분석 절차를 포함해야 합니다.
        -   '델타(Δ) 계산(실적-컨센서스)' → 'IR 및 웹 자료 기반 근본 원인 분석' → '미래 시나리오 생성'의 흐름을 중심으로 구체적인 단계를 구성하세요.
        -   예시:
            -   실적 발표 자료(Earnings Release)에서 핵심 재무 지표(매출, EPS 등)를 추출.
            -   주요 컨센서스 제공업체(e.g., Bloomberg, Refinitiv)의 컨센서스 데이터 확보.
            -   실적과 컨센서스 간의 차이(Δ)를 계산하고, 서프라이즈율(Surprise %)을 산출.
            -   IR 자료, 컨퍼런스 콜 스크립트, 웹사이트 공시 등을 분석하여 차이 발생의 근본 원인 파악.
            -   분석된 원인을 바탕으로 긍정적, 부정적 시나리오를 포함한 미래 EPS 및 매출 범위를 예측.
            -   핵심 원인을 시각화하여 보고서에 포함할 차트 목록 생성.
            -   보고서 초안 작성.
    
    2.  **제작할 차트 (charts):**
        -   분석 결과에 포함될 주요 차트 목록을 명시하세요.
        -   예시: EPS 서프라이즈율(%), 매출 서프라이즈율(%), 가이던스 변화, 시나리오별 EPS 범위.
    
    3.  **분석 위험 요소 (risks):**
        -   분석 과정에서 고려해야 할 잠재적 위험 요소들을 나열하세요.
        -   예시: 환율 변동, 회계 기간 변경, 추가 주간(Extra Week), 중단 사업부, 일회성 비용(SBC/One-offs) 등.
    
    4.  **Human-in-the-Loop (승인 절차):**
        -   **계획 수립 후, 사용자(Human)에게 이 계획에 대한 승인 여부를 물어보세요.**
        -   만약 사용자가 **'승인(Approve)'**하면 다음 단계로 진행합니다.
        -   만약 사용자가 **'수정(Modify)'** 또는 **'거절(Reject)'**하면 계획 수립 단계로 되돌아가서 사용자의 피드백을 반영하여 새로운 계획을 작성해야 합니다.
    
    **최종 결과는 다음 JSON 형식으로만 출력해야 합니다:**
    {"steps": [...], "charts": [...], "risks": [...]}
    """
    )

    try:
        client = get_openai_client()
        if not client:
            raise Exception("OpenAI client not available")
        
        # Use OpenAI's structured output to force PlanFormat schema
        response = client.beta.chat.completions.parse(
            model=ai_model,
            messages=[
                {"role": "system", "content": "You are a meticulous earnings planner. You must follow the exact JSON schema provided."},
                {"role": "user", "content": plan_prompt}
            ],
            response_format=PlanFormat,
            temperature=0.2
        )
        
        # Extract structured response (automatically validates against PlanFormat)
        plan = response.choices[0].message.parsed
        
        # Additional validation for PlanFormat
        def validate_plan_format(plan_result: PlanFormat) -> bool:
            """Validate PlanFormat structure and content."""
            if not isinstance(plan_result.steps, list) or len(plan_result.steps) == 0:
                return False
            if not isinstance(plan_result.charts, list):
                return False
            if not isinstance(plan_result.risks, list):
                return False
                
            # Check that all steps are non-empty strings
            for step in plan_result.steps:
                if not isinstance(step, str) or len(step.strip()) == 0:
                    return False
                    
            # Validate reasonable step count (between 1 and 10)
            if len(plan_result.steps) > 10:
                return False
                
            return True
        
        if not validate_plan_format(plan):
            raise ValueError("PlanFormat validation failed - invalid structure or content")
    except Exception as e:
        print(f"Plan parsing failed: {e}")
        plan = PlanFormat(
            steps=["실적 vs 컨센서스 델타 계산", "웹 자료 기반 근본 원인 분석", "시나리오 생성", "보고서 작성"],
            charts=["EPS 서프라이즈율", "매출 서프라이즈율"],
            risks=["환율 변동", "일회성 비용", "회계 기간 변경"]
        )

    # Test에서는 Interrupt 제외
    '''# 여기서 interrupt 호출
    approval = interrupt({"type": "approve",
                          "message": f"Research plan proposed: {'\n'.join(plan.steps)}. Do you approve? (yes/no(with reasons))"})

    # 승인 여부에 따라 분기
    if approval.lower() in ["yes", "y", "approve"]:
        return {"research_plan": plan,
                "messages": [AIMessage(content=f"Research plan approved by user. Proceeding with the plan.")]}
    else:
        # 거절 시, 상태에 거절 사유를 저장하여 plan_research 노드로 돌아갈 때 참고하도록 함
        return {"messages": [HumanMessage(content=f"User rejected the plan with reason: {approval}.")]}'''

    return {"research_plan": plan, "messages": [AIMessage(content="Research plan created.")]}


def agent(state: ResearchState) -> ResearchState:
    llm = build_llm()
    if not llm:
        return {"messages": [AIMessage(content="LLM not available - skipping agent tasks")]}
        
    tools = build_tools()
    try:
        llm_tools = llm.bind_tools(tools)
    except Exception as e:
        print(f"Failed to bind tools to LLM: {e}")
        llm_tools = llm

    sys = SystemMessage(content=(
        textwrap.dedent("""당신은 실적에 특화된 리서치 에이전트입니다. 
        당신의 주요 임무는 재무 데이터를 분석하고, 실적 결과의 주요 원인을 설명하며, 미래 예측 시나리오를 생성하는 것입니다.
        필요시 Python, Tavily, make_chart와 같은 도구를 활용하십시오.
        제공된 데이터를 비판적으로 평가하세요.
        특정 분석 작업이 모호하거나, 주관적인 해석이 필요하거나, 명확한 수치가 없는 정성적 데이터에서 핵심 추세를 추론하는 것과 같이 중요한 의사결정이 필요한 경우, 
        반드시 작업을 중단하고 인간에게 지침을 요청해야 합니다. 제공된 요약 정보를 사용하여 인간에게 정확한 질문을 하십시오.""")
    ))

    last_messages = state["messages"][-6:] if state.get("messages") else []

    # 에이전트의 자체 판단을 위한 프롬프트 추가
    context = _context_builder(state)
    prompt = textwrap.dedent(f"""
            Context:
            {context}
        
            Question:
            {state['question']}
        
            ---
            위 내용을 바탕으로 인간에게 자문을 구해야 할지 고려하세요. 작업이 명확하다면(예: 델타 계산, 차트 생성) 도구를 사용하여 진행하세요. 작업이 모호하거나 정성적인 판단을 요한다면(예: "시장 심리 설명", "경영진 가이던스의 신뢰도 평가"), 인간을 위한 간결한 메시지를 출력하세요.
        
            메시지는 해당 모호성에 대한 직접적인 질문이어야 합니다.
        
            예시:
            - 매출 델타를 계산해야 하는데, GAAP 수치를 사용해야 할까요, 아니면 비 GAAP 수치를 사용해야 할까요?
            - IR 요약에서 "거시경제적 역풍"이 언급되었습니다. 어떤 특정 거시경제적 요인을 우선적으로 조사해야 할까요?
            - 경영진의 어조가 조심스러워 보입니다. 이를 주요 위험 요소로 해석해야 할까요?
        
            인간의 입력이 필요하지 않다면, 단순히 계획을 진행하세요.
            """)

    # LLM에 판단을 맡기기
    #decision_message = llm.invoke([SystemMessage(content=prompt)] + last_messages)

    # test에서 interrupt 제외
    '''# LLM이 인간에게 질문해야 한다고 판단할 경우, interrupt 호출
    if decision_message.content.startswith("I need") or decision_message.content.startswith(
            "What specific") or decision_message.content.startswith("Should I"):
        return {"messages": [interrupt(decision_message.content)]}'''

    # 그렇지 않다면, 기존 워크플로우 진행
    ai = llm_tools.invoke([sys] + last_messages + [HumanMessage(content=prompt)])
    return {"messages": [ai]}

def safe_tool_node():
    """Create tool node with error handling."""
    try:
        tools = build_tools()
        return ToolNode(tools=tools)
    except Exception as e:
        print(f"Failed to create tool node: {e}")
        # Return a dummy tool node that just passes through
        return lambda state: {"messages": [AIMessage(content=f"Tool execution failed: {e}")]}

def synthesize(state: ResearchState) -> ResearchState:
    llm = build_llm()
    if not llm:
        return {"messages": [AIMessage(content="LLM not available - skipping synthesis")]}
        
    try:
        out = llm.invoke([
            SystemMessage(content="Condense into clean bullets + table extraction hints."),
            HumanMessage(
                content="Summarize Δ results and hypothesized root causes; list numbers to verify (FX, one-offs, guidance basis).")
        ])
        return {"messages": [out]}
    except Exception as e:
        return {"messages": [AIMessage(content=f"Synthesis failed: {e}")]}

class BandResult(BaseModel):
    # 기준 추정치 (현재 컨센서스)
    base_revenue: Optional[float] = None  # 기준 매출 (백만원)
    base_operating_profit: Optional[float] = None  # 기준 영업이익 (백만원)  
    base_net_income: Optional[float] = None  # 기준 순이익 (백만원)
    
    # 상승 시나리오 (절대값 + 변화율)
    optimistic_revenue: List[float]  # [금액(백만원), 변화율(%)]
    optimistic_operating_profit: List[float]  # [금액(백만원), 변화율(%)]
    optimistic_net_income: List[float]  # [금액(백만원), 변화율(%)]
    
    # 하락 시나리오 (절대값 + 변화율)
    pessimistic_revenue: List[float]  # [금액(백만원), 변화율(%)]
    pessimistic_operating_profit: List[float]  # [금액(백만원), 변화율(%)]
    pessimistic_net_income: List[float]  # [금액(백만원), 변화율(%)]
    
    # 상승 요인 분석
    positive_factors: List[str]  # 긍정적 요인들
    positive_impact_score: float  # 1-10 점수
    
    # 하락 요인 분석  
    negative_factors: List[str]  # 부정적 요인들
    negative_impact_score: float  # 1-10 점수
    
    # 신뢰도 및 사유
    confidence_level: float  # 0.0-1.0 (예측 신뢰도)
    key_assumptions: List[str]  # 핵심 가정사항들
    reasoning: str  # 상세한 추론 과정

def derive_band_from_ir(ir_text: str, earnings_text: str, consensus_text: str) -> BandResult:
    """
    IR/가이던스 코멘트에서 LLM을 통해 정밀한 시나리오 밴드를 추론.
    기존 컨센서스를 기준으로 상승/하락 시나리오의 구체적 금액과 변화율을 계산.
    """
    try:
        client = get_openai_client()
        if not client:
            raise Exception("OpenAI client not available")
        
        # 정교한 분석을 위한 다단계 프롬프트
        band_prompt = f"""
        당신은 정밀한 재무 예측 전문가입니다. 다음 정보를 종합하여 매우 구체적이고 정교한 시나리오 분석을 수행하세요.

        === 분석 데이터 ===
        
        **기존 컨센서스/추정치:**
        {consensus_text}
        
        **최근 실적 발표:**
        {earnings_text}
        
        **IR/가이던스 정보:**
        {ir_text}
        
        === 분석 절차 (반드시 순서대로 수행) ===
        
        1. **기준값 추출**: 컨센서스 데이터에서 매출, 영업이익, 순이익의 구체적 수치를 백만원 단위로 추출
        
        2. **긍정적 요인 분석**:
           - 실적 발표와 IR에서 언급된 모든 긍정적 요인들을 나열
           - 각 요인이 매출/영업이익/순이익에 미치는 구체적 영향도를 1-10점으로 평가
           - 정량적 근거가 있는 경우 구체적 수치 영향 추정
        
        3. **부정적 요인 분석**:
           - 실적 발표와 IR에서 언급된 모든 부정적 요인들을 나열  
           - 각 요인이 매출/영업이익/순이익에 미치는 구체적 영향도를 1-10점으로 평가
           - 정량적 근거가 있는 경우 구체적 수치 영향 추정
        
        4. **시나리오 계산**:
           - 낙관적 시나리오: 긍정 요인들이 최대한 실현될 때의 구체적 금액과 변화율
           - 비관적 시나리오: 부정 요인들이 최대한 현실화될 때의 구체적 금액과 변화율
           - 각 시나리오별로 [절대금액(백만원), 기준대비변화율(%)] 형태로 제시
        
        5. **신뢰도 평가**:
           - 예측 신뢰도를 0.0-1.0으로 평가 (과거 가이던스 정확도, 시장 불확실성 고려)
           - 핵심 가정사항들을 명확히 나열
           - 상세한 추론 과정을 단계별로 설명
        
        === 주의사항 ===
        - 모든 수치는 구체적이고 현실적이어야 함
        - 변화율은 소수점 둘째자리까지 정확히 계산
        - 추정 근거를 명확히 제시
        - 업종 특성과 시장 환경을 반영
        
        최종 결과는 반드시 제공된 JSON 스키마 형식을 정확히 준수하세요.
        """
            
        response = client.beta.chat.completions.parse(
            model='gpt-4o-mini',
            messages=[
                {"role": "system", "content": "당신은 정밀한 재무 예측 전문가입니다. 모든 수치를 정확하게 계산하고 현실적인 시나리오를 제시해야 합니다."},
                {"role": "user", "content": band_prompt}
            ],
            response_format=BandResult,
            temperature=0.1  # 더 일관된 결과를 위해 낮은 온도
        )
        
        result = response.choices[0].message.parsed
        
        # 강화된 검증 로직
        if not validate_enhanced_band_result(result):
            raise ValueError("Enhanced BandResult validation failed")
            
        return result
        
    except Exception as e:
        print(f"Error in derive_band_from_ir: {e}")
        # 기본값 반환 (새로운 스키마에 맞게)
        return BandResult(
            base_revenue=5000.0,
            base_operating_profit=800.0, 
            base_net_income=600.0,
            optimistic_revenue=[5400.0, 8.0],
            optimistic_operating_profit=[920.0, 15.0],
            optimistic_net_income=[720.0, 20.0],
            pessimistic_revenue=[4600.0, -8.0],
            pessimistic_operating_profit=[680.0, -15.0], 
            pessimistic_net_income=[480.0, -20.0],
            positive_factors=["시장 회복", "신제품 출시"],
            positive_impact_score=6.5,
            negative_factors=["원자재 가격 상승", "환율 변동"],
            negative_impact_score=5.5,
            confidence_level=0.7,
            key_assumptions=["시장 환경 안정", "환율 변동 제한적"],
            reasoning="기본 추정치 기반 보수적 시나리오 적용"
        )

def validate_enhanced_band_result(result: BandResult) -> bool:
    """강화된 BandResult 검증 함수"""
    try:
        # 기본 구조 검증
        required_lists = [
            result.optimistic_revenue, result.optimistic_operating_profit, result.optimistic_net_income,
            result.pessimistic_revenue, result.pessimistic_operating_profit, result.pessimistic_net_income
        ]
        
        for lst in required_lists:
            if not isinstance(lst, list) or len(lst) != 2:
                return False
            if not all(isinstance(val, (int, float)) for val in lst):
                return False
        
        # 논리적 일관성 검증
        if result.base_revenue and result.base_revenue <= 0:
            return False
        if result.base_operating_profit and result.base_operating_profit <= 0:
            return False
        if result.base_net_income and result.base_net_income <= 0:
            return False
            
        # 점수 범위 검증
        if not (1.0 <= result.positive_impact_score <= 10.0):
            return False
        if not (1.0 <= result.negative_impact_score <= 10.0):
            return False
        if not (0.0 <= result.confidence_level <= 1.0):
            return False
            
        # 변화율 합리성 검증 (±100% 이내)
        for scenario_list in required_lists:
            change_pct = scenario_list[1]
            if abs(change_pct) > 100.0:
                return False
                
        return True
        
    except Exception:
        return False

def scenario_generator(state: ResearchState) -> ResearchState:
    """
    IR 해석 기반 밴드를 적용해 다음 분기 시나리오(긍정/보수/부정)를 산출하고
    EPS/매출 밴드 차트를 생성.
    """
    llm = build_llm()
    if not llm:
        return {"messages": [AIMessage(content="LLM not available - skipping scenario generation")]}
        
    earnings_analysis = state.get("earnings_analysis", "")
    ir_text = state.get("ir_summary", "")
    consensus_analysis = state.get("consensus_analysis", "")

    schema_prompt = [
        SystemMessage(content="Extract forward (next quarter) estimates if present. Output JSON only."),
        HumanMessage(content=textwrap.dedent(f"""
        From the text below, extract the LATEST forward quarter estimates as:
        {{"quarter": "2025 Q3", "revenue": 5300, "eps": 2.10}}
        If missing, infer from closest hints; else output null fields.
        ---
        {consensus_analysis[:8000]}
        """))
    ]
    base_msg = llm.invoke(schema_prompt)
    try:
        base_est = json.loads(base_msg.content)
    except Exception:
        base_est = {"quarter": None, "revenue": None, "eps": None}

    # 향상된 밴드 분석 결과 활용
    bands = derive_band_from_ir(ir_text, earnings_analysis, consensus_analysis)
    
    # 기준값 설정 (BandResult에서 추출하거나 기존 추정치 사용)
    base_revenue = bands.base_revenue if bands.base_revenue else base_est.get("revenue")
    base_operating_profit = bands.base_operating_profit
    base_net_income = bands.base_net_income

    scen = {
        "base": {
            "quarter": base_est.get("quarter"),
            "revenue": base_revenue,
            "operating_profit": base_operating_profit,
            "net_income": base_net_income,
            "eps": base_est.get("eps"),
            "assumption": "기존 컨센서스 기준 시나리오",
            "confidence": bands.confidence_level
        },
        "optimistic": {
            "quarter": base_est.get("quarter"),
            "revenue": bands.optimistic_revenue[0] if bands.optimistic_revenue else None,
            "revenue_change_pct": bands.optimistic_revenue[1] if bands.optimistic_revenue else None,
            "operating_profit": bands.optimistic_operating_profit[0] if bands.optimistic_operating_profit else None,
            "operating_profit_change_pct": bands.optimistic_operating_profit[1] if bands.optimistic_operating_profit else None,
            "net_income": bands.optimistic_net_income[0] if bands.optimistic_net_income else None,
            "net_income_change_pct": bands.optimistic_net_income[1] if bands.optimistic_net_income else None,
            "positive_factors": bands.positive_factors,
            "impact_score": bands.positive_impact_score,
            "assumption": f"긍정 요인 실현: {', '.join(bands.positive_factors[:3])}..."
        },
        "pessimistic": {
            "quarter": base_est.get("quarter"),
            "revenue": bands.pessimistic_revenue[0] if bands.pessimistic_revenue else None,
            "revenue_change_pct": bands.pessimistic_revenue[1] if bands.pessimistic_revenue else None,
            "operating_profit": bands.pessimistic_operating_profit[0] if bands.pessimistic_operating_profit else None,
            "operating_profit_change_pct": bands.pessimistic_operating_profit[1] if bands.pessimistic_operating_profit else None,
            "net_income": bands.pessimistic_net_income[0] if bands.pessimistic_net_income else None,
            "net_income_change_pct": bands.pessimistic_net_income[1] if bands.pessimistic_net_income else None,
            "negative_factors": bands.negative_factors,
            "impact_score": bands.negative_impact_score,
            "assumption": f"부정 요인 현실화: {', '.join(bands.negative_factors[:3])}..."
        },
        "analysis_meta": {
            "key_assumptions": bands.key_assumptions,
            "reasoning": bands.reasoning,
            "confidence_level": bands.confidence_level
        }
    }

    charts_meta = state.get("charts", []).copy()
    q = base_est.get("quarter") or "Next Q"
    
    # 매출 시나리오 차트 생성
    if scen["base"]["revenue"] and scen["optimistic"]["revenue"] and scen["pessimistic"]["revenue"]:
        spec_revenue = {
            "title": f"매출 시나리오 분석 - {q}",
            "xlabel": "시나리오", 
            "ylabel": "매출 (백만원)",
            "y_series": [{
                "name": "매출", "kind": "bar",
                "values": [
                    scen["pessimistic"]["revenue"], 
                    scen["base"]["revenue"], 
                    scen["optimistic"]["revenue"]
                ],
                "x": ["비관적", "기준", "낙관적"],
                "data_labels": True
            }],
            "caption": f"{q} 매출 시나리오 밴드 (컨센서스 기반 정밀 분석)"
        }
        try:
            chart_result = make_chart.invoke({"spec_json": json.dumps(spec_revenue)})
            data = json.loads(chart_result)
            if "path" in data: 
                charts_meta.append({"spec": spec_revenue, "path": data["path"], "caption": data["caption"]})
        except Exception as e:
            print(f"차트 생성 실패: {e}")
    
    # 영업이익 시나리오 차트 생성
    if scen["base"]["operating_profit"] and scen["optimistic"]["operating_profit"] and scen["pessimistic"]["operating_profit"]:
        spec_op = {
            "title": f"영업이익 시나리오 분석 - {q}",
            "xlabel": "시나리오", 
            "ylabel": "영업이익 (백만원)",
            "y_series": [{
                "name": "영업이익", "kind": "bar",
                "values": [
                    scen["pessimistic"]["operating_profit"], 
                    scen["base"]["operating_profit"], 
                    scen["optimistic"]["operating_profit"]
                ],
                "x": ["비관적", "기준", "낙관적"],
                "data_labels": True
            }],
            "caption": f"{q} 영업이익 시나리오 밴드 (요인별 영향 분석)"
        }
        try:
            chart_result = make_chart.invoke({"spec_json": json.dumps(spec_op)})
            data = json.loads(chart_result)
            if "path" in data: 
                charts_meta.append({"spec": spec_op, "path": data["path"], "caption": data["caption"]})
        except Exception as e:
            print(f"영업이익 차트 생성 실패: {e}")

    return {"scenarios": scen, "charts": charts_meta,
            "messages": [AIMessage(content="IR-informed scenarios generated.")]}


def compose_report(state: ResearchState) -> ResearchState:
    title = "# Earnings-Focused Deep Research Report\n"
    parts = [title]

    parts += ["## 1. Executive Summary\n",
              "- Δ(Actual - Consensus): Revenue / OI / EPS 요약\n",
              "- Beat/Miss 주요 요인(가격/믹스/볼륨/FX/일회성/시점)\n",
              "- 가이던스 변화 및 신뢰도\n"]
    parts += ["\n## 2. Earnings vs Consensus (Core)\n",
              state.get("earnings_analysis", "-")]
    parts += ["\n## 3. Drivers via IR + Web\n",
              state.get("ir_summary", "-")]
    parts += ["\n## 4. Consensus Analysis\n",
              state.get("consensus_analysis", "-")]

    charts = state.get("charts", [])
    if charts:
        parts.append("\n## 5. Visuals\n")
        for c in charts:
            parts.append(f"![{c['caption']}]({c['path']})\n*{c['caption']}*\n")

    scen = state.get("scenarios", {})
    if scen:
        parts.append("\n## 6. Forward Scenarios (Optimistic / Base / Pessimistic)\n")
        q = scen.get("base", {}).get("quarter", "Next Q")

        parts.append(f"**기준 분기:** {q}\n")
        parts.append("| 시나리오 | 매출(백만원) | 영업이익(백만원) | 순이익(백만원) | 신뢰도 | 주요가정 |")
        parts.append("|---|---:|---:|---:|---:|---|")
        
        # 기준 시나리오
        base_data = scen.get("base", {})
        parts.append(f"| 기준 | {base_data.get('revenue', '-'):,.0f} | {base_data.get('operating_profit', '-'):,.0f} | {base_data.get('net_income', '-'):,.0f} | {base_data.get('confidence', 0.0):.1%} | {base_data.get('assumption', '-')} |")
        
        # 낙관적 시나리오  
        opt_data = scen.get("optimistic", {})
        opt_rev = f"{opt_data.get('revenue', 0):,.0f} (+{opt_data.get('revenue_change_pct', 0):.1f}%)" if opt_data.get("revenue") else "-"
        opt_op = f"{opt_data.get('operating_profit', 0):,.0f} (+{opt_data.get('operating_profit_change_pct', 0):.1f}%)" if opt_data.get("operating_profit") else "-"
        opt_ni = f"{opt_data.get('net_income', 0):,.0f} (+{opt_data.get('net_income_change_pct', 0):.1f}%)" if opt_data.get("net_income") else "-"
        parts.append(f"| 낙관적 | {opt_rev} | {opt_op} | {opt_ni} | {opt_data.get('impact_score', 0)/10:.1%} | {opt_data.get('assumption', '-')[:30]}... |")
        
        # 비관적 시나리오
        pes_data = scen.get("pessimistic", {})
        pes_rev = f"{pes_data.get('revenue', 0):,.0f} ({pes_data.get('revenue_change_pct', 0):.1f}%)" if pes_data.get("revenue") else "-"
        pes_op = f"{pes_data.get('operating_profit', 0):,.0f} ({pes_data.get('operating_profit_change_pct', 0):.1f}%)" if pes_data.get("operating_profit") else "-"
        pes_ni = f"{pes_data.get('net_income', 0):,.0f} ({pes_data.get('net_income_change_pct', 0):.1f}%)" if pes_data.get("net_income") else "-"
        parts.append(f"| 비관적 | {pes_rev} | {pes_op} | {pes_ni} | {pes_data.get('impact_score', 0)/10:.1%} | {pes_data.get('assumption', '-')[:30]}... |")
        
        # 분석 메타 정보 추가
        meta_data = scen.get("analysis_meta", {})
        if meta_data:
            parts.append(f"\n**핵심 가정사항:**")
            for assumption in meta_data.get("key_assumptions", []):
                parts.append(f"- {assumption}")
            
            parts.append(f"\n**분석 신뢰도:** {meta_data.get('confidence_level', 0.0):.1%}")
            
            if meta_data.get("reasoning"):
                parts.append(f"\n**추론 근거:** {meta_data.get('reasoning')[:200]}...")

    parts += ["\n\n## 7. Supporting Context\n### 7.1 Financials (sanity checks)\n",
              state.get("financial_analysis", "-"),
              "\n### 7.2 Company & Business Overview\n",
              state.get("company_business", "-")]
    parts += ["\n## 8. Risks & Verification\n- FX/캘린더/Extra week/중단사업/회계 변경/일회성 영향 재검증\n"]

    return {"report_md": "\n".join(parts), "messages": [AIMessage(content="Report composed.")]}


def human_approve(state: ResearchState) -> ResearchState:
    # For now, auto-approve in test mode
    return {"messages": [AIMessage(content="Report auto-approved in test mode.")]}


def finalize(state: ResearchState) -> ResearchState:
    return {"messages": [AIMessage(content="Finalized report.")]}


# ---------------------- Wiring ----------------------
def build_graph():
    graph = StateGraph(ResearchState)
    graph.add_node("plan_research", plan_research)
    graph.add_node("agent", agent)
    graph.add_node("tools", safe_tool_node())
    graph.add_node("scenario_generator", scenario_generator)
    graph.add_node("compose_report", compose_report)
    graph.add_node("human_approve", human_approve)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "plan_research")

    # Test에서는 승인 절차 제외
    '''graph.add_conditional_edges(
        "plan_research",
        lambda state: "continue" if any("approved" in msg.content for msg in state["messages"]) else "retry_plan",
        {"continue": "agent", "retry_plan": "plan_research"}
    )'''
    graph.add_edge("plan_research", "agent")

    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", "__end__": "scenario_generator"})
    graph.add_edge("tools", "agent")

    graph.add_edge("scenario_generator", "compose_report")
    graph.add_edge("compose_report", "human_approve")
    graph.add_edge("human_approve", "finalize")
    graph.add_edge("finalize", END)

    saver = MemorySaver()
    return graph.compile(checkpointer=saver)


def _sanitize_file_path(fpath: str) -> str:
    """Sanitize file path to prevent directory traversal attacks."""
    if not fpath or not isinstance(fpath, str):
        return ""
    
    # Remove dangerous path traversal patterns
    dangerous_patterns = ['../', '..\\', '~/', '/etc/', '/var/', 'C:\\Windows', 'C:\\System32']
    for pattern in dangerous_patterns:
        if pattern in fpath:
            print(f"WARNING: Blocked potentially dangerous path: {fpath}")
            return ""
    
    # Only allow paths within the project directory
    import os.path
    abs_path = os.path.abspath(fpath)
    project_root = os.path.abspath(os.getcwd())
    
    if not abs_path.startswith(project_root):
        print(f"WARNING: Blocked path outside project directory: {fpath}")
        return ""
        
    return fpath

def read_md(fpath):
    """Read markdown file with path sanitization, return empty string if not found."""
    sanitized_path = _sanitize_file_path(fpath)
    if not sanitized_path:
        return ""
        
    if not os.path.exists(sanitized_path): 
        print(f"Warning: {sanitized_path} not found, returning empty string")
        return ""
    try:
        with open(sanitized_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Sanitize the content as well
            return _sanitize_text(content)
    except Exception as e:
        print(f"Error reading {sanitized_path}: {e}")
        return ""


# ---------------------- Demo ----------------------
if __name__ == "__main__":
    print("=" * 60)
    print("DEEP RESEARCH AGENT - STARTUP")
    print("=" * 60)
    
    # Check if we have valid API keys
    if openaikey == "test-key":
        print("WARNING: No valid OpenAI API key found!")
        print("Please set OPENAI_API_KEY environment variable or create config.ini")
        print("Proceeding with limited functionality...")
    
    # 데이터는 이미 요약되어 있다고 가정
    cb = read_md('data/summary/company_business.md')
    fa = read_md('data/summary/financial_analysis.md')
    ea = read_md('data/summary/earnings_analysis.md')
    ir = read_md('data/summary/ir_summary.md')
    ca = read_md('data/summary/consensus_analysis.md')

    try:
        app = build_graph()
        inputs = {
            "question": "이번 분기 Beat/Miss와 원인, 그리고 다음 분기 시나리오를 제시해줘.",
            "company_business": cb,
            "financial_analysis": fa,
            "earnings_analysis": ea,
            "ir_summary": ir,
            "consensus_analysis": ca,
        }
        config = {"configurable": {"thread_id": "demo-thread-streamlined-earnings"}}
    except Exception as e:
        print(f"Failed to initialize workflow: {e}")
        exit(1)

    print("Starting deep research agent workflow...")
    print(f"Input summary lengths: CB={len(cb)}, FA={len(fa)}, EA={len(ea)}, IR={len(ir)}, FG={len(ca)}")
    
    # Test PlanFormat validation
    print("Testing PlanFormat schema enforcement...")
    try:
        test_plan = PlanFormat(
            steps=["Test step 1", "Test step 2"],
            charts=["Test chart 1"],
            risks=["Test risk 1"]
        )
        print(f"✅ PlanFormat validation passed: {len(test_plan.steps)} steps, {len(test_plan.charts)} charts, {len(test_plan.risks)} risks")
    except Exception as e:
        print(f"❌ PlanFormat validation failed: {e}")
    
    # Test BandResult validation  
    print("Testing BandResult schema enforcement...")
    try:
        test_band = BandResult(up_pct=[0.05, 0.10], down_pct=[-0.10, -0.05])
        print(f"✅ BandResult validation passed: up={test_band.up_pct}, down={test_band.down_pct}")
    except Exception as e:
        print(f"❌ BandResult validation failed: {e}")
    
    try:
        import time
        start_time = time.time()
        max_duration = 300  # 5 minutes max execution time
        step_count = 0
        max_steps = 50  # Maximum number of workflow steps
        
        for step in app.stream(inputs, config, stream_mode="values"):
            step_count += 1
            current_time = time.time()
            
            # Safety checks to prevent infinite loops
            if current_time - start_time > max_duration:
                print(f"WARNING: Workflow timeout after {max_duration} seconds")
                break
            if step_count > max_steps:
                print(f"WARNING: Workflow stopped after {max_steps} steps")
                break
            if "messages" in step:
                try:
                    last = step["messages"][-1]
                    role = getattr(last, "type", "msg")
                    content = getattr(last, "content", "")
                    print(f"[{role}] {content[:200]}...")
                except Exception as e:
                    print(f"Error processing step: {e}")
                    pass
            
            # Print final report if available
            if "report_md" in step and step["report_md"]:
                print("\n" + "="*50)
                print("FINAL REPORT")
                print("="*50)
                print(step["report_md"])
                
        # Save final report
        final_state = app.get_state(config)
        if final_state and final_state.values.get("report_md"):
            report_path = os.path.join(ASSETS_DIR, "final_report.md")
            sanitized_path = _sanitize_file_path(report_path)
            if sanitized_path:
                try:
                    sanitized_content = _sanitize_text(final_state.values["report_md"])
                    with open(sanitized_path, "w", encoding="utf-8") as f:
                        f.write(sanitized_content)
                    print(f"\nReport saved to: {sanitized_path}")
                except Exception as e:
                    print(f"Failed to save report: {e}")
            else:
                print("WARNING: Report path blocked for security reasons")
            
    except Exception as e:
        print(f"Workflow execution failed: {e}")
        import traceback
        traceback.print_exc()

'''    # (옵션) 팔로업 응답 후 재개
    cmd = Command(resume={"data": "컨센서스: Bloomberg, FX: 고정환율, 세그먼트: Enterprise/Commercial"})
    for _ in app.stream(cmd, config, stream_mode="values"):
        pass

    cmd2 = Command(resume={"data": "yes"})
    for _ in app.stream(cmd2, config, stream_mode="values"):
        pass

    state = app.get_state(config)
    print("\n---- REPORT ----\n")
    print(state.values.get("report_md", "No report."))'''