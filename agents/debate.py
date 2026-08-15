import asyncio
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from models.schemas import DebateResult

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 2000
_JUDGE_MAX_TOKENS = 4000

_client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

BULL_SYSTEM = (
    "你是坚定的多头研究员。从共同信息基础中找出所有支持买入的证据。"
    "规则：只能用提供的数据，每个论点必须引用具体数字，"
    "可以选择性忽略对你不利的数据，不得使用让步词（但是/然而）。"
    "输出：3-5个核心多头论点，每条50字以内，最后一句：多头评分：X/10"
)

BEAR_SYSTEM = (
    "你是坚定的空头研究员。从共同信息基础中找出所有支持做空或回避的证据。"
    "规则：只能用提供的数据，每个论点必须引用具体数字，"
    "可以选择性忽略对你不利的数据，不得使用让步词。"
    "输出：3-5个核心空头论点，每条50字以内，最后一句：空头评分：X/10"
)

BULL_REBUTTAL_SYSTEM = (
    "你是多头研究员，进入反驳轮。针对空头每条论点逐一反驳，"
    "只能引用共同信息基础中的数据。"
    "最后一句：维持多头评分：X/10 或 修正多头评分：X/10（原因：）"
)

BEAR_REBUTTAL_SYSTEM = (
    "你是空头研究员，进入反驳轮。针对多头每条论点逐一反驳，"
    "只能引用共同信息基础中的数据。"
    "最后一句：维持空头评分：X/10 或 修正空头评分：X/10（原因：）"
)

JUDGE_SYSTEM = (
    "你是中立的投资委员会主席。综合双方辩论给出裁决。"
    "裁决结构：\n"
    "1. 双方最强论点各一条\n"
    "2. 双方最弱/最被反驳的论点各一条\n"
    "3. 最关键的1-2个不确定因素\n"
    "4. 最终建议：[强烈关注/可以建仓/观望等待/回避]，附一句理由\n"
    "5. 置信度：X/10，并说明为何不是10/10\n"
    "注意：你不预测股价，你评估论点说服力。"
)


def _build_context(ticker: str, fundamental: str, sentiment: str, technical: str) -> str:
    return (
        f"【共同信息基础 - {ticker}】\n\n"
        f"=== 基本面分析 ===\n{fundamental}\n\n"
        f"=== 情绪分析 ===\n{sentiment}\n\n"
        f"=== 技术面分析 ===\n{technical}"
    )


async def _call(system: str, user: str, max_tokens: int = _MAX_TOKENS) -> str:
    response = await _client.messages.create(
        model=_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


async def run_debate(
    ticker: str,
    fundamental: str,
    sentiment: str,
    technical: str,
) -> DebateResult:
    context = _build_context(ticker, fundamental, sentiment, technical)

    # 第一轮：多空并行立论
    bull_case, bear_case = await asyncio.gather(
        _call(BULL_SYSTEM, f"请对以下信息给出多头立场：\n\n{context}"),
        _call(BEAR_SYSTEM, f"请对以下信息给出空头立场：\n\n{context}"),
    )

    # 第二轮：双方能看到对方第一轮，并行反驳
    bull_rebuttal_prompt = (
        f"{context}\n\n"
        f"=== 多头第一轮立论 ===\n{bull_case}\n\n"
        f"=== 空头第一轮立论（你需要逐一反驳）===\n{bear_case}"
    )
    bear_rebuttal_prompt = (
        f"{context}\n\n"
        f"=== 空头第一轮立论 ===\n{bear_case}\n\n"
        f"=== 多头第一轮立论（你需要逐一反驳）===\n{bull_case}"
    )

    bull_rebuttal, bear_rebuttal = await asyncio.gather(
        _call(BULL_REBUTTAL_SYSTEM, bull_rebuttal_prompt),
        _call(BEAR_REBUTTAL_SYSTEM, bear_rebuttal_prompt),
    )

    # 第三轮：裁判看完所有内容后裁决
    judge_prompt = (
        f"{context}\n\n"
        f"=== 多头立论 ===\n{bull_case}\n\n"
        f"=== 空头立论 ===\n{bear_case}\n\n"
        f"=== 多头反驳 ===\n{bull_rebuttal}\n\n"
        f"=== 空头反驳 ===\n{bear_rebuttal}\n\n"
        "请综合以上辩论内容，给出裁决。"
    )
    verdict = await _call(JUDGE_SYSTEM, judge_prompt, max_tokens=_JUDGE_MAX_TOKENS)

    return DebateResult(
        ticker=ticker,
        bull_case=bull_case,
        bear_case=bear_case,
        bull_rebuttal=bull_rebuttal,
        bear_rebuttal=bear_rebuttal,
        verdict=verdict,
    )
