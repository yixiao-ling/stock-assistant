# 美股投研助手

基于 Claude API 的个人美股投研工具，支持个股综合分析（基本面/情绪/技术面三 Agent 并行）、财报 PDF 上传解读（RAG）、多空辩论（Bull/Bear/Judge）和持仓感知顾问（私人 AI 顾问，结合你的真实持仓给出个性化建议）。所有分析均基于实时 yfinance 行情和 NewsAPI 新闻，本地运行，数据不上传。

## 安装

```bash
pip install -r requirements.txt
```

复制环境变量模板并填入你的 API Key：

```bash
cp .env.example .env
# 编辑 .env，填入 ANTHROPIC_API_KEY 和 NEWS_API_KEY
```

## 运行

```bash
streamlit run app.py
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
