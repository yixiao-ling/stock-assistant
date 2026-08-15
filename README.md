# 美股投研助手

基于 DeepSeek API 的个人美股投研工具，支持个股综合分析（基本面/情绪/技术面三 Agent 并行）、财报 PDF 上传解读（RAG）、多空辩论（Bull/Bear/Judge）、持仓感知顾问（私人 AI 顾问，结合你的真实持仓给出个性化建议），以及基于 TradingAgents（LangGraph 12-agent 流程）的深度研究与决策复盘。所有分析均基于实时 yfinance 行情和 NewsAPI 新闻，本地运行，数据不上传。

## 安装

```bash
pip install -r requirements.txt
```

深度研究功能需要额外安装 TradingAgents（单独仓库，`pip install -e` 引入）：

```bash
git clone -b sa-integration https://github.com/yixiao-ling/TradingAgents.git ../TradingAgents
pip install -e ../TradingAgents
```

复制环境变量模板并填入你的 API Key：

```bash
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY、NEWS_API_KEY、SA_DEEP_TOKEN
```

## 运行

```bash
uvicorn api:app --reload
```

## 持仓数据

编辑 `data/portfolio/mock_data.json` 修改你的持仓：

```json
{
  "cash": 8500,
  "positions": [
    {"ticker": "NVDA", "shares": 50, "avg_cost": 180.5},
    {"ticker": "AAPL", "shares": 100, "avg_cost": 165.2}
  ]
}
```

启动后点击侧边栏「🔄 刷新持仓」即可加载。
