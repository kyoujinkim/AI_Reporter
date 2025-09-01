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
    research_plan: Dict[str, Any]

    tables: Dict[str, Any]
    charts: List[Dict[str, Any]]

    scenario_params: Dict[str, Any]
    scenarios: Dict[str, Any]

    report_md: str


# ---------------------- Globals ----------------------
ASSETS_DIR = os.path.join(os.getcwd(), "report_assets");
os.makedirs(ASSETS_DIR, exist_ok=True)

config = configparser.ConfigParser()
config.read("config.ini")
openaikey = config.get("openai", "API_KEY")

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
    tavily = TavilySearch(api_key=os.environ.get("TAVILY_API_KEY", ""), max_results=2, topic="finance")
    py = PythonREPLTool()
    return [tavily, py, make_chart]


def build_llm():
    model_id = os.environ.get("LLM_MODEL", "openai:gpt-4o-mini")
    return init_chat_model(model_id, api_key=openaikey)

class PlanFormat(BaseModel):
    steps: List[str]
    followups: List[str]
    charts: List[str]
    risks: List[str]

# ---------------------- Nodes ----------------------
def plan_research(state: ResearchState) -> ResearchState:
    plan_prompt = textwrap.dedent("""
    You are an meticulous earnings planner. Create a compact JSON plan with:
    - steps (<=8) focused on Δ calc, IR+web root-cause, and forward scenario generation
    - followups (e.g., consensus vendor, FX basis, segment defs)
    - charts: EPS surprise %, Revenue surprise %, Guidance change, Scenario EPS band
    - risks: FX normalization, calendar shifts, extra week, discontinued ops, SBC/one-offs
    Output JSON as:
    {"steps": [...], "followups": [...], "charts": [...], "risks": [...]}
    """)

    msg = client.responses.parse(
        model = 'gpt-4o-mini',
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
                "followups": [], "charts": [], "risks": ["cross-check 2+ sources"]}
    if plan.get("followups"):
        human = interrupt({"type": "followups", "questions": plan["followups"]})
        return {"messages": [HumanMessage(content=f"[User answers] {human}")], "research_plan": plan}
    return {"research_plan": plan, "messages": [AIMessage(content="Plan generated.")]}


def agent(state: ResearchState) -> ResearchState:
    llm = build_llm()
    tools = build_tools()
    llm_tools = llm.bind_tools(tools)

    sys = SystemMessage(content=(
        "You are an Earnings-Focused Research Agent. Your primary goal is to analyze financial data, "
        "explain the drivers of earnings results, and generate forward-looking scenarios. "
        "Use tools (Python, Tavily, make_chart) when necessary. "
        "Critically evaluate the provided data. If a specific analysis task is ambiguous, requires "
        "subjective interpretation, or involves a high-stakes decision (e.g., inferring a key "
        "trend from qualitative data without clear numbers), you must interrupt and ask for human guidance. "
        "Use the provided summaries and ask precise questions to the human."
    ))

    last_messages = state["messages"][-6:] if state.get("messages") else []

    # 에이전트의 자체 판단을 위한 프롬프트 추가
    context = _context_builder(state)
    prompt = textwrap.dedent(f"""
        Context:
        {context[:10000]}

        Question:
        {state['question']}

        ---
        Based on the above, consider if a human should be consulted. If the task is clear (e.g., calculate delta, make a chart), proceed with tools. If the task is ambiguous or requires qualitative judgment (e.g., "explain market sentiment," "assess the confidence of management guidance"), output a concise message for the human.

        The message should be a direct question about the specific ambiguity.

        Examples:
        - I need to calculate the revenue delta, should I use GAAP or non-GAAP numbers?
        - The IR summary mentions "macro headwinds." What specific macro factors should I prioritize investigating?
        - Management's tone seems cautious. Should I interpret this as a major risk factor?

        If no human input is required, simply proceed with your plan.
        """)

    # LLM에 판단을 맡기기
    decision_message = llm.invoke([SystemMessage(content=prompt)] + last_messages)

    # LLM이 인간에게 질문해야 한다고 판단할 경우, interrupt 호출
    if decision_message.content.startswith("I need") or decision_message.content.startswith(
            "What specific") or decision_message.content.startswith("Should I"):
        return {"messages": [interrupt(decision_message.content)]}

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


def derive_band_from_ir(ir_text: str, earnings_text: str = "") -> dict:
    """
    IR/가이던스 코멘트에서 신호를 추출해 밴드 폭을 결정.
    반환: {"up_pct": [lo, hi], "down_pct": [lo, hi]}  # 퍼센트(소수)
    우선순위: 명시 가이던스 범위 > 정성 신호 점수
    """
    ir = (ir_text or "").lower()
    earn = (earnings_text or "").lower()

    # (기존 로직 유지)
    import re
    rev_rng = re.findall(r"(revenue|sales)[^\d]{0,20}(\d+[.,]?\d*)\s*[-~]\s*(\d+[.,]?\d*)", ir)
    eps_rng = re.findall(r"(eps)[^\d]{0,20}(\d+[.,]?\d*)\s*[-~]\s*(\d+[.,]?\d*)", ir)

    guidance_hint = None
    if rev_rng:
        lo, hi = float(rev_rng[0][1].replace(',', '')), float(rev_rng[0][2].replace(',', ''))
        width = (hi - lo) / max(lo, 1e-9)
        guidance_hint = ("revenue", max(min(width, 0.25), 0.02))
    elif eps_rng:
        lo, hi = float(eps_rng[0][1].replace(',', '')), float(eps_rng[0][2].replace(',', ''))
        width = (hi - lo) / max(lo, 1e-9)
        guidance_hint = ("eps", max(min(width, 0.30), 0.03))

    signals = {
        "demand_up": any(k in ir for k in
                         ["strong demand", "robust demand", "accelerating demand", "backlog up", "bookings up",
                          "record backlog", "pipeline expansion", "healthy funnel", "sequential improvement"]),
        "demand_down": any(k in ir for k in
                           ["weak demand", "soft demand", "sluggish", "macro headwind", "inventory correction",
                            "order pushout", "delays", "shortfall"]),
        "pricing_up": any(k in ir for k in
                          ["price increase", "pricing power", "favorable pricing", "mix improvement", "premium tier"]),
        "pricing_down": any(
            k in ir for k in ["price pressure", "discounting", "competitive pricing", "unfavorable mix"]),
        "cost_up": any(
            k in ir for k in ["cost inflation", "input costs up", "wage pressure", "energy cost up", "freight up"]),
        "cost_down": any(k in ir for k in
                         ["cost down", "efficiency gains", "opex discipline", "productivity", "scale benefits",
                          "gross margin expansion"]),
        "fx_tail": any(k in ir for k in ["fx tailwind", "currency tailwind"]),
        "fx_head": any(k in ir for k in ["fx headwind", "currency headwind"]),
        "supply_up": any(
            k in ir for k in ["supply improvement", "capacity increase", "lead time improved", "yields up"]),
        "supply_down": any(k in ir for k in ["supply constraint", "capacity constraint", "component shortage",
                                             "manufacturing disruption"]),
        "guide_up": any(k in ir for k in ["raise guidance", "increase guidance", "above guidance", "upgraded outlook"]),
        "guide_down": any(
            k in ir for k in ["lower guidance", "reduce guidance", "below guidance", "downgraded outlook"]),
        "new_prod": any(k in ir for k in ["new product", "launch", "adoption", "attach rate", "land-and-expand"]),
    }

    w = {
        "demand_up": +3, "demand_down": -3,
        "pricing_up": +2, "pricing_down": -2,
        "cost_down": +2, "cost_up": -2,
        "fx_tail": +1, "fx_head": -1,
        "supply_up": +1, "supply_down": -2,
        "guide_up": +3, "guide_down": -3,
        "new_prod": +2,
    }
    score = sum(w[k] for k, v in signals.items() if v and k in w)

    def to_band(base_lo_hi=(0.06, 0.08), score=0):
        base_lo, base_hi = base_lo_hi
        adj = max(min(score, 10), -10) * 0.015
        lo = max(0.02, base_lo + adj)
        hi = max(lo + 0.01, base_hi + adj)
        return (lo, hi)

    up_lo, up_hi = to_band((0.06, 0.08), score)
    dn_lo, dn_hi = to_band((0.06, 0.08), -score)

    if guidance_hint:
        _, width = guidance_hint
        up_lo = max(0.02, width * 0.8)
        up_hi = max(up_lo + 0.01, width * 1.2)
        dn_lo = max(0.02, width * 0.8)
        dn_hi = max(dn_lo + 0.01, width * 1.2)

    return {"up_pct": [round(up_lo, 4), round(up_hi, 4)],
            "down_pct": [-round(dn_hi, 4), -round(dn_lo, 4)]}


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