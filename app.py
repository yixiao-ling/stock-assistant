import asyncio
import os
import tempfile

import anthropic
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from agents.analyst import run_full_analysis
from agents.debate import run_debate
from agents.portfolio_advisor import portfolio_advisor_agent
from data.portfolio.loader import load_portfolio
from data.portfolio.risk_analyzer import (
    analyze_concentration_risk,
    analyze_macro_exposure,
    analyze_sector_risk,
    build_investor_profile,
)
from data.rag import load_and_chunk_pdf, query_filings, store_chunks

st.set_page_config(page_title="美股投研助手", page_icon="📈", layout="wide")

# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _load_portfolio() -> tuple:
    """加载持仓，moomoo 不可用时 fallback 到 mock。返回 (profile, source)。"""
    try:
        raw = load_portfolio("mock")
        profile = build_investor_profile(raw["positions"], cash=raw["cash"])
        return profile, "mock"
    except Exception as e:
        return None, f"error: {e}"


def _find_position(profile, ticker: str):
    if profile is None:
        return None
    return next((p for p in profile.positions if p.ticker == ticker.upper()), None)


def _pnl_badge(pnl_pct: float) -> str:
    color = "#16a34a" if pnl_pct >= 0 else "#dc2626"
    sign = "+" if pnl_pct >= 0 else ""
    return f'<span style="background:{color};color:white;padding:2px 8px;border-radius:12px;font-size:0.85rem">{sign}{pnl_pct:.1f}%</span>'


def _rag_answer(ticker: str, question: str, chunks: list[str]) -> str:
    context = "\n\n---\n\n".join(chunks)
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=600,
        system="你是财报分析师，只根据提供的财报原文回答问题，引用原文数字，不做额外推断。",
        messages=[{"role": "user", "content": f"【财报摘录 - {ticker}】\n{context}\n\n【问题】{question}"}],
    )
    return response.content[0].text


# ── Session State 初始化 ───────────────────────────────────────────────────────

if "profile" not in st.session_state:
    st.session_state.profile = None
if "portfolio_source" not in st.session_state:
    st.session_state.portfolio_source = None
if "advisor_history" not in st.session_state:
    st.session_state.advisor_history = []  # list of (scenario, answer)

# ── 侧边栏 ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("📊 持仓面板")

    moomoo_connected = False  # moomoo OpenD 暂未接入
    dot = "🟢" if moomoo_connected else "🔴"
    status_label = "moomoo 已连接" if moomoo_connected else "moomoo 未连接（使用 Mock 数据）"
    st.markdown(f"{dot} **{status_label}**")

    if st.button("🔄 刷新持仓"):
        with st.spinner("加载持仓..."):
            profile, source = _load_portfolio()
            st.session_state.profile = profile
            st.session_state.portfolio_source = source

    if st.session_state.profile is None:
        with st.spinner("初始化持仓..."):
            profile, source = _load_portfolio()
            st.session_state.profile = profile
            st.session_state.portfolio_source = source

    profile = st.session_state.profile
    if profile:
        st.metric("总仓位价值", f"${profile.total_value:,.0f}")
        col_a, col_b = st.columns(2)
        col_a.metric("持仓数", profile.num_positions)
        col_b.metric("现金比", f"{profile.cash_ratio*100:.1f}%")

        st.markdown("**各持仓占比**")
        for p in sorted(profile.positions, key=lambda x: -x.weight):
            pnl_sign = "+" if p.unrealized_pnl_pct >= 0 else ""
            st.markdown(
                f"- **{p.ticker}** {p.weight*100:.1f}% "
                f"({pnl_sign}{p.unrealized_pnl_pct:.1f}%)"
            )

# ── 主体 Tabs ─────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs(["📈 个股分析", "📄 财报解读", "⚔️ 多空辩论", "🧭 持仓顾问"])

# ── Tab 1：个股分析 ───────────────────────────────────────────────────────────

with tab1:
    st.header("个股综合分析")

    col_input, col_btn = st.columns([4, 1])
    with col_input:
        ticker_input = st.text_input("", placeholder="例如 NVDA、AAPL、MSFT")
    with col_btn:
        analyze_btn = st.button("开始分析")

    if analyze_btn and ticker_input.strip():
        ticker = ticker_input.strip().upper()

        # 持仓上下文 badge
        pos = _find_position(st.session_state.profile, ticker)
        if pos:
            pnl_sign = "+" if pos.unrealized_pnl_pct >= 0 else ""
            st.markdown(
                f"**持仓上下文：** {ticker} · {pos.shares:.0f}股 · "
                f"成本 ${pos.avg_cost:.2f} | 现价 ${pos.current_price:.2f} | "
                f"仓位 {pos.weight*100:.1f}% · "
                f"浮盈 {_pnl_badge(pos.unrealized_pnl_pct)}",
                unsafe_allow_html=True,
            )

        extra_context = ""
        if pos:
            extra_context = (
                f"该用户已持有 {ticker} {pos.shares:.0f} 股，成本 ${pos.avg_cost:.2f}，"
                f"当前浮盈 {pos.unrealized_pnl_pct:+.1f}%，仓位占比 {pos.weight*100:.1f}%。"
            )

        with st.spinner(f"正在并行分析 {ticker}..."):
            result = asyncio.run(run_full_analysis(ticker, extra_context=extra_context))

        # ── 摘要卡片（三列，只显示核心结论）────────────────────────────────
        st.markdown("---")
        c1, c2, c3 = st.columns(3)

        def _first_line(text):
            for line in text.splitlines():
                line = line.strip().lstrip("#").strip()
                if line:
                    return line
            return text[:80]

        with c1:
            st.markdown("**📊 基本面**")
            st.markdown(_first_line(result["fundamental"]))

        with c2:
            st.markdown("**📰 市场情绪**")
            st.markdown(_first_line(result["sentiment"]))

        with c3:
            st.markdown("**📉 技术面**")
            st.markdown(_first_line(result["technical"]))

        # ── 详情折叠区 ───────────────────────────────────────────────────────
        st.markdown("---")
        st.subheader("📋 整合报告")
        st.markdown(result["synthesis"])
        with st.expander("📊 基本面详情", expanded=False):
            st.markdown(result["fundamental"])
        with st.expander("📰 情绪详情", expanded=False):
            st.markdown(result["sentiment"])
        with st.expander("📉 技术面详情", expanded=False):
            st.markdown(result["technical"])

# ── Tab 2：财报解读 ───────────────────────────────────────────────────────────

with tab2:
    st.header("财报 PDF 解读（RAG）")

    col_l, col_r = st.columns([1, 1])

    with col_l:
        uploaded = st.file_uploader("上传财报 PDF", type=["pdf"])
        ticker_rag = st.text_input("股票代码（关联 collection）", placeholder="例如 NVDA")

    with col_r:
        question = st.text_area("提问", placeholder="例如：本季度营收和利润率如何？主要风险因素有哪些？", height=120)
        rag_btn = st.button("开始解读")

    if rag_btn:
        if not uploaded:
            st.warning("请先上传 PDF 文件。")
        elif not ticker_rag.strip():
            st.warning("请输入股票代码。")
        elif not question.strip():
            st.warning("请输入问题。")
        else:
            ticker_rag = ticker_rag.strip().upper()

            with st.spinner("解析 PDF 并建立索引..."):
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(uploaded.read())
                    tmp_path = tmp.name

                chunks = load_and_chunk_pdf(tmp_path, ticker_rag)
                store_chunks(ticker_rag, chunks)
                os.unlink(tmp_path)

            st.success(f"已建立索引：{len(chunks)} 个 chunks")

            with st.spinner("检索相关段落并生成答案..."):
                retrieved = query_filings(ticker_rag, question, top_k=5)
                answer = _rag_answer(ticker_rag, question, retrieved)

            st.subheader("💡 分析结果")
            st.markdown(answer)

            with st.expander("📎 检索到的原文段落", expanded=False):
                for i, chunk in enumerate(retrieved, 1):
                    st.markdown(f"**段落 {i}**")
                    st.text(chunk[:500] + ("..." if len(chunk) > 500 else ""))
                    st.markdown("---")

# ── Tab 3：多空辩论 ───────────────────────────────────────────────────────────

with tab3:
    st.header("⚔️ 多空辩论")

    col_d_input, col_d_btn = st.columns([4, 1])
    with col_d_input:
        debate_ticker = st.text_input(
            "", placeholder="例如 NVDA、TSLA、MSFT",
            key="debate_ticker",
        )
    with col_d_btn:
        debate_btn = st.button("开始辩论", key="debate_btn")

    if debate_btn and debate_ticker.strip():
        dticker = debate_ticker.strip().upper()

        # 持仓背景信息
        dpos = _find_position(st.session_state.profile, dticker)
        if dpos:
            st.markdown(
                f"**持仓背景：** {dticker} · "
                f"{dpos.shares:.0f}股 · 成本 ${dpos.avg_cost:.2f} · 现价 ${dpos.current_price:.2f} · "
                f"仓位 {dpos.weight*100:.1f}% · "
                f"浮盈 {_pnl_badge(dpos.unrealized_pnl_pct)}",
                unsafe_allow_html=True,
            )
            st.caption("ℹ️ 该股票在您的持仓中，辩论结论将影响再平衡决策。")

        with st.spinner(f"第一步：并行获取 {dticker} 基础分析..."):
            analysis = asyncio.run(run_full_analysis(dticker))

        with st.spinner("第二步：多空双方同时立论..."):
            debate = asyncio.run(
                run_debate(
                    dticker,
                    analysis["fundamental"],
                    analysis["sentiment"],
                    analysis["technical"],
                )
            )

        st.markdown("---")
        st.subheader(f"{dticker} 辩论结果")

        # 折叠区：四个辩论环节
        with st.expander("📈 多头立论", expanded=True):
            st.markdown(debate.bull_case)

        with st.expander("📉 空头立论", expanded=True):
            st.markdown(debate.bear_case)

        with st.expander("⚔️ 多头反驳", expanded=False):
            st.markdown(debate.bull_rebuttal)

        with st.expander("🛡️ 空头反驳", expanded=False):
            st.markdown(debate.bear_rebuttal)

        # 裁判结论：直接显示 + 边框高亮
        st.markdown("---")
        st.subheader("⚖️ 裁判结论")
        st.markdown(
            f'<div style="border:2px solid #3b82f6;border-radius:8px;padding:16px 20px;">'
            f"{debate.verdict}"
            f"</div>",
            unsafe_allow_html=True,
        )

# ── Tab 4：持仓顾问 ───────────────────────────────────────────────────────────

_PRESET_SCENARIOS = [
    "美联储加息50bp",
    "中美贸易摩擦升级",
    "美股大盘回调20%",
    "自定义",
]

_MACRO_LABELS = {
    "interest_rate_sensitive": "利率敏感",
    "usd_strength": "美元强弱",
    "geopolitical_risk": "地缘风险",
    "consumer_confidence": "消费信心",
}

_LEVEL_COLOR = {"高": "#ef4444", "中": "#f59e0b", "低": "#22c55e"}


def _sector_pie(sector_concentration: dict) -> go.Figure:
    labels = list(sector_concentration.keys())
    values = [v * 100 for v in sector_concentration.values()]
    fig = go.Figure(go.Pie(
        labels=labels, values=values,
        hole=0.45,
        textinfo="label+percent",
        hovertemplate="%{label}: %{value:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        margin=dict(t=10, b=10, l=10, r=10),
        height=260,
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def _hbar(items: list[tuple[str, float, str]]) -> go.Figure:
    """items = [(label, value_0_to_1, color), ...]"""
    labels = [i[0] for i in items]
    values = [i[1] * 100 for i in items]
    colors = [i[2] for i in items]
    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        marker_color=colors,
        text=[f"{v:.1f}%" for v in values],
        textposition="outside",
        hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        margin=dict(t=4, b=4, l=10, r=50),
        height=max(120, len(items) * 44),
        xaxis=dict(range=[0, 130], showgrid=False, visible=False),
        yaxis=dict(showgrid=False, automargin=True),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


with tab4:
    st.header("🧭 持仓顾问")

    profile = st.session_state.profile
    if profile is None:
        st.warning("请先在侧边栏点击「刷新持仓」加载持仓数据。")
    else:
        conc   = analyze_concentration_risk(profile)
        sector = analyze_sector_risk(profile)
        macro  = analyze_macro_exposure(profile)

        # ── 区域一：持仓概览 ─────────────────────────────────────────────────
        st.subheader("📊 持仓概览")

        # 饼图独占一行
        st.plotly_chart(_sector_pie(profile.sector_concentration))

        # metric 三列（顶层，不嵌套）
        m1, m2, m3 = st.columns(3)
        m1.metric("总仓位", f"${profile.total_value:,.0f}")
        m2.metric("最大单仓", f"{profile.top_holding_weight*100:.1f}%")
        m3.metric("HHI 集中度", f"{sector['hhi']:.3f}")

        st.caption(f"行业集中度评级：**{sector['concentration_level']}**　｜　"
                   f"风险偏好：**{profile.risk_preference}**　｜　"
                   f"持仓数：{profile.num_positions}　｜　"
                   f"现金比：{profile.cash_ratio*100:.1f}%")

        # 风险信号
        alerts = conc.get("alerts", [])
        if alerts:
            for a in alerts:
                level = "🔴" if "高危" in a else "🟡"
                color = "#fef2f2" if "高危" in a else "#fffbeb"
                border = "#ef4444" if "高危" in a else "#f59e0b"
                st.markdown(
                    f'<div style="background:{color};border-left:4px solid {border};'
                    f'padding:6px 12px;border-radius:4px;margin:4px 0;">'
                    f"{level} {a}</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.success("✅ 无集中度高危警告")

        st.markdown("---")

        # ── 区域二：风险分析 ─────────────────────────────────────────────────
        st.subheader("⚠️ 风险分析")

        r1, r2 = st.columns(2)

        with r1:
            st.markdown("**单股集中风险**")
            pos_items = sorted(
                [(p.ticker, p.weight,
                  "#ef4444" if p.weight > 0.20 else "#f59e0b" if p.weight > 0.10 else "#22c55e")
                 for p in profile.positions],
                key=lambda x: -x[1],
            )
            st.plotly_chart(_hbar(pos_items))

        with r2:
            st.markdown("**行业集中风险**")
            sec_items = [
                (k, v, "#ef4444" if v > 0.40 else "#f59e0b" if v > 0.25 else "#22c55e")
                for k, v in sorted(profile.sector_concentration.items(), key=lambda x: -x[1])
            ]
            st.plotly_chart(_hbar(sec_items))

        st.markdown("**宏观敞口**")
        macro_items = [
            (_MACRO_LABELS.get(k, k), v["weight"], _LEVEL_COLOR[v["level"]])
            for k, v in macro.items()
        ]
        st.plotly_chart(_hbar(macro_items))

        st.markdown("---")

        # ── 区域三：AI 顾问对话 ──────────────────────────────────────────────
        st.subheader("🤖 AI 顾问对话")

        adv_col1, adv_col2 = st.columns([3, 1])
        with adv_col1:
            scenario_choice = st.selectbox(
                "选择宏观情景", _PRESET_SCENARIOS, key="scenario_select"
            )
        with adv_col2:
            ask_btn = st.button("问顾问")

        custom_scenario = ""
        if scenario_choice == "自定义":
            custom_scenario = st.text_input(
                "描述您的宏观情景", placeholder="例如：日元大幅贬值，日本央行被迫加息"
            )

        scenario_text = custom_scenario if scenario_choice == "自定义" else scenario_choice

        if ask_btn and scenario_text:
            with st.spinner("AI 顾问分析中..."):
                answer = asyncio.run(
                    portfolio_advisor_agent(profile, conc, sector, macro, scenario=scenario_text)
                )
            entry = (scenario_text, answer)
            st.session_state.advisor_history = ([entry] + st.session_state.advisor_history)[:3]

        # 对话气泡展示（最近3条，最新在上）
        for scenario_label, answer_text in st.session_state.advisor_history:
            st.markdown(
                f'<div style="background:#eff6ff;border-radius:8px;padding:8px 14px;'
                f'margin:6px 0 2px 0;font-size:0.88rem;color:#1e40af;">'
                f"💬 <b>场景：</b>{scenario_label}</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;'
                f'padding:14px 18px;margin:0 0 12px 0;">'
                f"{answer_text}</div>",
                unsafe_allow_html=True,
            )
