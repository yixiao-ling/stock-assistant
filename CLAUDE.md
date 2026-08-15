# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述
个人美股投研助手，Python 后端 + HTML/CSS/JS 前端（Bloomberg Terminal 深色风格）。
核心功能：个股分析、财报RAG解读、多空辩论、持仓顾问。

## 技术栈
- LLM：DeepSeek API（deepseek-chat，快速分析路径 / deepseek-reasoner，TradingAgents 深度研究路径），通过 `openai.AsyncOpenAI`（`base_url="https://api.deepseek.com"`，OpenAI 兼容接口）调用
- 数据：yfinance + NewsAPI
- 向量库：ChromaDB（本地，./chroma_db）
- 持仓数据：Mock（data/portfolio/mock_data.json）
- 前端：index.html + FastAPI（api.py）

## 运行命令

```bash
pip install -r requirements.txt

# 主入口：FastAPI + index.html
uvicorn api:app --reload
```

环境变量（`.env`）：`DEEPSEEK_API_KEY`、`NEWS_API_KEY`、`SA_DEEP_TOKEN`（深度研究接口口令）

## 验证命令

```bash
python -c "from models.schemas import Position, InvestorProfile, DebateResult; print('models OK')"
python -c "from data.portfolio.loader import load_portfolio; print(load_portfolio('mock'))"
```

## 架构与数据流

### API 层（api.py）
FastAPI 暴露四个端点，同时 serve `index.html`：
- `POST /analyze/{ticker}` → `agents/analyst.py::run_full_analysis`
- `POST /debate/{ticker}` → `agents/debate.py::run_debate`（接收三份分析报告作为请求体）
- `GET /portfolio` → `data/portfolio/risk_analyzer.py` 计算持仓风险指标
- `POST /advisor` → `agents/portfolio_advisor.py::portfolio_advisor_agent`（接收可选宏观场景）

### Agent 层（agents/）

**analyst.py** — 四步流程，三并行 + 一串行：
1. `fundamental_agent` — 基本面，yfinance info
2. `sentiment_agent` — 新闻情绪，NewsAPI
3. `technical_agent` — 技术面，仅用价格/52周高低推断 RSI/MACD
4. `_synthesis_agent` — 整合三份报告，`max_tokens=4000`

所有 Agent 接受可选 `extra_context: str`，用于注入持仓背景信息。

**debate.py** — 三轮五次 LLM 调用：
1. 多头立论 + 空头立论（并行）
2. 多头反驳 + 空头反驳（并行，双方能看到对方第一轮）
3. 裁判综合裁决（串行）
返回 `DebateResult` dataclass。

**portfolio_advisor.py** — 两个函数：
- `portfolio_advisor_agent` — 持仓整体顾问，不拉取实时行情
- `analyze_ticker_with_portfolio_context` — 结合持仓对单只股票分析（已持有 vs 未持有两种不同 prompt 路径）

### 数据层（data/）

**stock_data.py**：`get_stock_data` 调 yfinance，`get_news` 调 NewsAPI（默认7天，最多20条）

**portfolio/loader.py**：读取 `mock_data.json`，格式 `{"cash": float, "positions": [{"ticker", "shares", "avg_cost"}]}`

**portfolio/risk_analyzer.py**：
- `build_investor_profile` — 调 yfinance 拿实时价格，计算权重/盈亏/行业集中度/风险偏好（aggressive/moderate/conservative）
- `analyze_concentration_risk` / `analyze_sector_risk` / `analyze_macro_exposure` — 纯计算，不调 LLM

**rag.py**：ChromaDB，按 ticker 分 collection（`{ticker}_filings`），chunk 2000 chars；`query_filings` 做语义检索

### 数据模型（models/schemas.py）
三个 `@dataclass`：`Position`、`InvestorProfile`、`DebateResult`

## 硬性规则

### Never
- Never 修改 `agents/` 和 `data/` 下的任何文件，除非明确说"修改XX文件"
- Never 使用 moomoo API
- Never 一次修改超过一个模块，除非明确要求
- Never 把 LLM API 调用的 `max_tokens` 设低于：
  - 单项 Agent（基本面/情绪/技术面）：800
  - 整合报告/辩论裁判/持仓顾问：3000

### Always
- Always 修改前告诉用户会动哪些文件
- Always 修改后告诉用户改了哪几行
- Always 修改完立刻运行验证命令确认没有报错
- Always 用 `.strip().upper()` 处理用户输入的 ticker

### When
- When 图表数值超过50%，确保标签用 `textposition='outside'` 且 x轴range留余量
- When 用户说"只改XX"，严格只动那一个文件
