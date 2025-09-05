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
config.read("D:/config.ini")
openaikey = config.get("openai", "API_KEY")
tavilykey = config.get("tavily", "API_KEY_NH")

ai_model = "gpt-4o-mini"

# ---------------------- Client ----------------------
client = OpenAI(api_key=openaikey)


# ---------------------- Utils ----------------------
def est_tokens(text: str) -> int:
    return max(1, int(len(text or "") / 4))


def _context_builder(state: ResearchState) -> str:
    """Provides combined context from pre-summarized data."""
    ctx_parts = ["[Summaries (from provided input)]"]
    for name, text in [
        ("earnings_analysis", state.get("earnings_analysis")),
        ("ir_summary", state.get("ir_summary")),
        ("financial_analysis", state.get("financial_analysis")),
        ("company_business", state.get("company_business")),
    ]:
        if text: ctx_parts.append(f"- {name}:\n{text}")
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
    tavily = TavilySearch(tavily_api_key=tavilykey, max_results=2, topic="finance")
    py = PythonREPLTool()
    return [tavily, py, make_chart]


def build_llm():
    return init_chat_model("openai:"+ai_model, api_key=openaikey)

class PlanFormat(BaseModel):
    steps: List[str]
    charts: List[str]
    risks: List[str]

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

    msg = client.responses.parse(
        model = ai_model,
        input = [
            {"role":"system", "content":"You are a meticulous earnings planner. Output compact JSON."},
            {"role":"user", "content": plan_prompt}
        ],
        text_format=PlanFormat,
    )

    try:
        plan = msg.output_parsed
    except Exception:
        plan = {"steps": ["Δ calc", "web root-cause", "scenarios", "report"],
                "charts": [], "risks": ["cross-check 2+ sources"]}

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
    tools = build_tools()
    llm_tools = llm.bind_tools(tools)

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

tool_node = ToolNode(tools=build_tools())

def synthesize(state: ResearchState) -> ResearchState:
    llm = build_llm()
    out = llm.invoke([
        SystemMessage(content="Condense into clean bullets + table extraction hints."),
        HumanMessage(
            content="Summarize Δ results and hypothesized root causes; list numbers to verify (FX, one-offs, guidance basis).")
    ])
    return {"messages": [out]}

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
        msg = client.responses.parse(
            model='gpt-4o-mini',
            input=[
                {"role": "system", "content": "당신은 매우 꼼꼼한 실적 플래너입니다. 반드시 간결한 JSON만 출력하세요."},
                {"role": "user", "content": prompt}
            ],
            text_format=BandResult,
        )
        result = msg.output_parsed
        if not (isinstance(result.up_pct, list) and len(result.up_pct) == 2 and
                isinstance(result.down_pct, list) and len(result.down_pct) == 2):
            raise ValueError("Invalid band format")
        return result
    except Exception:
        return BandResult(up_pct=[0.06, 0.08], down_pct=[-0.08, -0.06])

def scenario_generator(state: ResearchState) -> ResearchState:
    """
    IR 해석 기반 밴드를 적용해 다음 분기 시나리오(긍정/보수/부정)를 산출하고
    EPS/매출 밴드 차트를 생성.
    """
    llm = build_llm()
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
    up_lo, up_hi = bands["up_pct"]
    dn_lo, dn_hi = bands["down_pct"]

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
        data = json.loads(make_chart.run(json.dumps(spec_eps)))
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
    approval = interrupt({"type": "approve", "message": "보고서 발행해도 될까요? (yes/no)"})
    return {"messages": [HumanMessage(content=f"User approval: {approval}")]}


def finalize(state: ResearchState) -> ResearchState:
    return {"messages": [AIMessage(content="Finalized report.")]}


# ---------------------- Wiring ----------------------
def build_graph():
    graph = StateGraph(ResearchState)
    graph.add_node("plan_research", plan_research)
    graph.add_node("agent", agent)
    graph.add_node("tools", tool_node)
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


def read_md(fpath):
    if not os.path.exists(fpath): return ""
    with open(fpath, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------- Demo ----------------------
if __name__ == "__main__":
    # 데이터는 이미 요약되어 있다고 가정
    cb = read_md('data/summary/company_business.md')
    fa = read_md('data/summary/financial_analysis.md')
    ea = read_md('data/summary/earnings_analysis.md')
    ir = read_md('data/summary/ir_summary.md')

    app = build_graph()
    inputs = {
        "question": "이번 분기 Beat/Miss와 원인, 그리고 다음 분기 시나리오를 제시해줘.",
        "company_business": cb,
        "financial_analysis": fa,
        "earnings_analysis": ea,
        "ir_summary": ir,
    }
    config = {"configurable": {"thread_id": "demo-thread-streamlined-earnings"}}

    for step in app.stream(inputs, config, stream_mode="values"):
        if "messages" in step:
            try:
                last = step["messages"][-1]
                role = getattr(last, "type", "msg")
                content = getattr(last, "content", "")
                print(f"[{role}] {content[:200]}...")
            except:
                pass

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