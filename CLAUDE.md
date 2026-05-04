# 美股投研助手 — Claude Code 配置

## 项目概述
个人美股投研助手，Python 后端 + 前端 UI。
核心功能：个股分析、财报RAG解读、多空辩论、持仓顾问。

## 技术栈
- LLM：Claude API（claude-opus-4-5）
- 数据：yfinance + NewsAPI
- 向量库：ChromaDB（本地，./chroma_db）
- 持仓数据：Mock（data/portfolio/mock_data.json）
- 前端：待重写为 HTML/CSS/JS + FastAPI

## 关键文件
- agents/analyst.py     # 基本面/情绪/技术面三个Agent
- agents/debate.py      # 牛熊辩论系统
- agents/portfolio_advisor.py  # 持仓感知顾问
- data/stock_data.py    # yfinance + NewsAPI
- data/portfolio/loader.py     # 持仓数据加载
- data/rag.py           # ChromaDB + PDF解读
- models/schemas.py     # 数据模型

## 已确认可用的模块
- 三个分析Agent并行调用 ✅
- 持仓感知联动（extra_context注入）✅
- 辩论系统（Bull/Bear/Judge）✅
- ChromaDB RAG ✅
- Mock持仓数据 ✅

## 硬性规则

### Never
- Never 修改 agents/ 和 data/ 下的任何文件，除非我明确说"修改XX文件"
- Never 使用 moomoo API（已放弃，用mock数据）
- Never 一次修改超过一个模块，除非我明确要求
- Never 在 Claude API 调用里把 max_tokens 设低于以下值：
  - 单项Agent（基本面/情绪/技术面）：800
  - 整合报告/辩论裁判/持仓顾问：3000

### Always
- Always 修改前告诉我会动哪些文件
- Always 修改后告诉我改了哪几行
- Always 修改完立刻运行验证命令确认没有报错
- Always 用 .strip().upper() 处理用户输入的 ticker

### When
- When 遇到 Streamlit 兼容性报错，先检查 use_container_width 等新版参数
- When 图表数值超过50%，确保标签用 textposition='outside' 且 x轴range留余量
- When 用户说"只改XX"，严格只动那一个文件

## 当前待办
- [ ] 重写前端：Streamlit → HTML/CSS/JS（Bloomberg Terminal 深色风格）
- [ ] 创建 api.py：用 FastAPI 暴露后端接口

## 常用验证命令
python -c "from models.schemas import Position, InvestorProfile, DebateResult; print('models OK')"
python -c "from data.portfolio.loader import load_portfolio; print(load_portfolio('mock'))"
streamlit run app.py  # 旧前端，待替换
