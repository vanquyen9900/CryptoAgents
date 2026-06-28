import re
from tradingagents.agents.utils.agent_utils import get_language_instruction


def _parse_confidence(text: str) -> float:
    """Extract the last CONFIDENCE: X.XX value from the LLM output.

    Returns 0.5 (neutral) on any parse failure so the debate loop
    never crashes due to a malformed response (report §3.5 spec).
    """
    matches = re.findall(r"CONFIDENCE:\s*([0-9]*\.?[0-9]+)", text, re.IGNORECASE)
    if not matches:
        return 0.5
    try:
        value = float(matches[-1])
        return max(0.0, min(1.0, value))
    except ValueError:
        return 0.5


def create_bull_researcher(llm):
    def bull_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bull_history = investment_debate_state.get("bull_history", "")

        current_response = investment_debate_state.get("current_response", "")
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        regime_report = state.get("regime_report", "")
        asset_type = state.get("asset_type", "stock")
        target_label = "stock" if asset_type == "stock" else "asset"
        fundamentals_label = (
            "Company fundamentals report"
            if asset_type == "stock"
            else "Asset fundamentals report (may be unavailable for crypto)"
        )
        regime_section = (
            f"\nMarket regime analysis (TensorFlow HMM Bull/Bear/Sideway detection): {regime_report}"
            if regime_report
            else ""
        )

        prompt = f"""You are a Bull Analyst advocating for investing in the {target_label}. Your task is to build a strong, evidence-based case emphasizing growth potential, competitive advantages, and positive market indicators. Leverage the provided research and data to address concerns and counter bearish arguments effectively.

Key points to focus on:
- Growth Potential: Highlight the asset's market opportunities, momentum signals, and scalability.
- Competitive Advantages: Emphasize factors like unique value proposition, strong adoption, or dominant market positioning.
- Positive Indicators: Use technical health, favorable market regime, risk condition, and recent positive news as evidence.
- Bear Counterpoints: Critically analyze the bear argument with specific data and sound reasoning, addressing concerns thoroughly and showing why the bull perspective holds stronger merit.
- Engagement: Present your argument in a conversational style, engaging directly with the bear analyst's points and debating effectively rather than just listing data.

Resources available:
Market research report: {market_research_report}
Social media sentiment report: {sentiment_report}
Latest world affairs news: {news_report}
{fundamentals_label}: {fundamentals_report}{regime_section}
Conversation history of the debate: {history}
Last bear argument: {current_response}
Use this information to deliver a compelling bull argument, refute the bear's concerns, and engage in a dynamic debate that demonstrates the strengths of the bull position.

After your argument, on its own line, write your confidence score in this exact format:
CONFIDENCE: <value between 0.00 and 1.00>
Where 1.00 = absolute conviction to buy, 0.50 = neutral/uncertain, 0.00 = no conviction.
""" + get_language_instruction()

        response = llm.invoke(prompt)
        raw_content = response.content

        # D — Adaptive Debate: parse confidence score (report §3.5)
        bull_confidence = _parse_confidence(raw_content)

        argument = f"Bull Analyst: {raw_content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bull_history": bull_history + "\n" + argument,
            "bear_history": investment_debate_state.get("bear_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
            "bull_confidence": bull_confidence,
            "bear_confidence": investment_debate_state.get("bear_confidence", 0.5),
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bull_node
