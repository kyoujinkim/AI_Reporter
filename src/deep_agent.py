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
    decision_message = llm.invoke([SystemMessage(content=prompt)] + last_messages)

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
    up_pct: List[float]   # [lo, hi]
    down_pct: List[float] # [lo, hi] (음수)

def derive_band_from_ir(ir_text: str, earnings_text: str = "") -> BandResult:
    """
    IR/가이던스 코멘트에서 LLM을 통해 단계적 사유로 시나리오 밴드(상승/하락 퍼센트)를 추론.
    반환: BandResult (up_pct/down_pct는 각각 [lo, hi] 리스트)
    """
    prompt = [
        SystemMessage(content=(
            "당신은 금융 애널리스트입니다. IR/가이던스와 실적 요약을 바탕으로, 합리적인 낙관적(상승) 및 비관적(하락) 시나리오 밴드(퍼센트, 예: 0.05 = +5%)를 단계적으로 사유하여 추정하세요.\n"
            "다음 단계를 반드시 따르세요:\n"
            "1. IR/가이던스와 실적 요약에서 긍정적 요인과 부정적 요인을 모두 나열하세요.\n"
            "2. 각 요인이 실적에 미칠 영향(방향: 상승/하락, 강도: 약함/보통/강함)을 추정하세요.\n"
            "3. 모든 요인의 영향을 종합하여, 합리적인 낙관적(상승) 및 비관적(하락) 밴드(퍼센트 범위)를 산출하세요.\n"
            "최종적으로 아래 JSON 형식으로만 결과를 출력하세요:\n"
            "{\"up_pct\": [lo, hi], \"down_pct\": [lo, hi]}"
        )),
        HumanMessage(content=f"""IR/가이던스:\n{ir_text}\n\n실적 요약:\n{earnings_text}\n\n출력 형식:\n{{"up_pct": [lo, hi], "down_pct": [lo, hi]}}""")
    ]
    try:
        client = get_openai_client()
        if not client:
            raise Exception("OpenAI client not available")
        
        # Create structured prompt for BandResult
        band_prompt = f"""
        다음 IR/가이던스와 실적 요약을 바탕으로 합리적인 낙관적(상승) 및 비관적(하락) 시나리오 밴드를 추정하세요.
        
        단계:
        1. IR/가이던스와 실적 요약에서 긍정적 요인과 부정적 요인을 분석
        2. 각 요인이 실적에 미칠 영향의 방향과 강도를 평가
        3. 종합적으로 낙관적(상승) 및 비관적(하락) 밴드를 퍼센트로 산출 (예: 0.05 = +5%)
        
        IR/가이던스:
        {ir_text}
        
        실적 요약:
        {earnings_text}
        
        up_pct는 [최소%, 최대%] 상승 범위를, down_pct는 [최소%, 최대%] 하락 범위를 나타냅니다.
        """
            
        response = client.beta.chat.completions.parse(
            model='gpt-4o-mini',
            messages=[
                {"role": "system", "content": "당신은 매우 꼼꼼한 실적 플래너입니다. 제공된 스키마를 정확히 따라야 합니다."},
                {"role": "user", "content": band_prompt}
            ],
            response_format=BandResult,
            temperature=0.2
        )
        
        # Extract structured response (automatically validates against BandResult)
        result = response.choices[0].message.parsed
        
        # Additional validation to ensure data integrity
        def validate_band_result(band_result: BandResult) -> bool:
            """Validate BandResult structure and values."""
            if not (isinstance(band_result.up_pct, list) and len(band_result.up_pct) == 2):
                return False
            if not (isinstance(band_result.down_pct, list) and len(band_result.down_pct) == 2):
                return False
            
            # Check that all values are numbers and in reasonable ranges
            all_values = band_result.up_pct + band_result.down_pct
            for val in all_values:
                if not isinstance(val, (int, float)):
                    return False
                if abs(val) > 1.0:  # More than 100% change seems unreasonable
                    return False
            
            # Check logical consistency: up_pct should be positive, down_pct should be negative
            if any(val < 0 for val in band_result.up_pct):
                return False
            if any(val > 0 for val in band_result.down_pct):
                return False
                
            return True
        
        if not validate_band_result(result):
            raise ValueError("BandResult validation failed - invalid structure or values")
            
        return result
    except Exception:
        return BandResult(up_pct=[0.06, 0.08], down_pct=[-0.08, -0.06])

def scenario_generator(state: ResearchState) -> ResearchState:
    """
    IR 해석 기반 밴드를 적용해 다음 분기 시나리오(긍정/보수/부정)를 산출하고
    EPS/매출 밴드 차트를 생성.
    """
    llm = build_llm()
    if not llm:
        return {"messages": [AIMessage(content="LLM not available - skipping scenario generation")]}
        
    earnings_summary = state.get("earnings_analysis", "")
    ir_text = state.get("ir_summary", "")

    schema_prompt = [
        SystemMessage(content="Extract forward (next quarter) estimates if present. Output JSON only."),
        HumanMessage(content=textwrap.dedent(f"""
        From the text below, extract the LATEST forward quarter estimates as:
        {{"quarter": "2025 Q3", "revenue": 5300, "eps": 2.10}}
        If missing, infer from closest hints; else output null fields.
        ---
        {earnings_summary[:8000]}
        """))
    ]
    base_msg = llm.invoke(schema_prompt)
    try:
        base_est = json.loads(base_msg.content)
    except Exception:
        base_est = {"quarter": None, "revenue": None, "eps": None}

    bands = derive_band_from_ir(ir_text, earnings_summary)
    up_lo, up_hi = bands.up_pct
    dn_lo, dn_hi = bands.down_pct

    def rng_pct(val, lo_pct, hi_pct):
        if val is None: return [None, None]
        lo = round(val * (1 + lo_pct), 2)
        hi = round(val * (1 + hi_pct), 2)
        return [min(lo, hi), max(lo, hi)]

    scen = {
        "base": {
            "quarter": base_est.get("quarter"),
            "revenue": base_est.get("revenue"),
            "eps": base_est.get("eps"),
            "assumption": "Maintain consensus/base demand & cost profile."
        },
        "optimistic": {
            "quarter": base_est.get("quarter"),
            "revenue_range": rng_pct(base_est.get("revenue"), up_lo, up_hi),
            "eps_range": rng_pct(base_est.get("eps"), up_lo, up_hi),
            "assumption": "IR-tailwinds: demand/pricing/mix/cost improvements as indicated."
        },
        "pessimistic": {
            "quarter": base_est.get("quarter"),
            "revenue_range": rng_pct(base_est.get("revenue"), dn_lo, dn_hi),
            "eps_range": rng_pct(base_est.get("eps"), dn_lo, dn_hi),
            "assumption": "IR-headwinds: macro/FX/competition/supply or guidance tone downbeat."
        }
    }

    charts_meta = state.get("charts", []).copy()
    q = base_est.get("quarter") or "Next Q"
    if base_est.get("eps") is not None:
        spec_eps = {
            "title": f"EPS Scenario Band - {q}", "x": ["Pessimistic", "Base", "Optimistic"],
            "y_series": [{
                "name": "EPS", "kind": "bar",
                "values": [scen["pessimistic"]["eps_range"][0], scen["base"]["eps"], scen["optimistic"]["eps_range"][1]]
            }],
            "xlabel": "Scenario", "ylabel": "EPS", "caption": f"{q} EPS scenario band (IR-informed)"
        }
        chart_result = make_chart.invoke({"spec_json": json.dumps(spec_eps)})
        data = json.loads(chart_result)
        if "path" in data: charts_meta.append({"spec": spec_eps, "path": data["path"], "caption": data["caption"]})

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

    charts = state.get("charts", [])
    if charts:
        parts.append("\n## 4. Visuals\n")
        for c in charts:
            parts.append(f"![{c['caption']}]({c['path']})\n*{c['caption']}*\n")

    scen = state.get("scenarios", {})
    if scen:
        parts.append("\n## 5. Forward Scenarios (Optimistic / Base / Pessimistic)\n")
        q = scen.get("base", {}).get("quarter", "Next Q")

        def row(label, rev, eps, asm):
            return f"| {label} | {rev} | {eps} | {asm} |"

        parts.append(f"**기준 분기:** {q}\n")
        parts.append("| 시나리오 | 매출 | EPS | 가정 |\n|---|---|---|---|")
        base_rev = scen.get("base", {}).get("revenue")
        base_eps = scen.get("base", {}).get("eps")
        opt_rev = scen.get("optimistic", {}).get("revenue_range")
        opt_eps = scen.get("optimistic", {}).get("eps_range")
        pes_rev = scen.get("pessimistic", {}).get("revenue_range")
        pes_eps = scen.get("pessimistic", {}).get("eps_range")
        parts.append(row("긍정",
                         f"{opt_rev[0]}~{opt_rev[1]}" if opt_rev and None not in opt_rev else "-",
                         f"{opt_eps[0]}~{opt_eps[1]}" if opt_eps and None not in opt_eps else "-",
                         scen.get("optimistic", {}).get("assumption", "-")))
        parts.append(row("보수",
                         f"{base_rev}" if base_rev is not None else "-",
                         f"{base_eps}" if base_eps is not None else "-",
                         scen.get("base", {}).get("assumption", "-")))
        parts.append(row("부정",
                         f"{pes_rev[0]}~{pes_rev[1]}" if pes_rev and None not in pes_rev else "-",
                         f"{pes_eps[0]}~{pes_eps[1]}" if pes_eps and None not in pes_eps else "-",
                         scen.get("pessimistic", {}).get("assumption", "-")))

    parts += ["\n\n## 6. Supporting Context\n### 6.1 Financials (sanity checks)\n",
              state.get("financial_analysis", "-"),
              "\n### 6.2 Company & Business Overview\n",
              state.get("company_business", "-")]
    parts += ["\n## 7. Risks & Verification\n- FX/캘린더/Extra week/중단사업/회계 변경/일회성 영향 재검증\n"]

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

    try:
        app = build_graph()
        inputs = {
            "question": "이번 분기 Beat/Miss와 원인, 그리고 다음 분기 시나리오를 제시해줘.",
            "company_business": cb,
            "financial_analysis": fa,
            "earnings_analysis": ea,
            "ir_summary": ir,
        }
        config = {"configurable": {"thread_id": "demo-thread-streamlined-earnings"}}
    except Exception as e:
        print(f"Failed to initialize workflow: {e}")
        exit(1)

    print("Starting deep research agent workflow...")
    print(f"Input summary lengths: CB={len(cb)}, FA={len(fa)}, EA={len(ea)}, IR={len(ir)}")
    
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