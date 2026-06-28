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


def create_bear_researcher(llm):
    def bear_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bear_history = investment_debate_state.get("bear_history", "")

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

        prompt = f"""You are a Bear Analyst making the case against investing in the {target_label}. Your goal is to present a well-reasoned argument emphasizing risks, challenges, and negative indicators. Leverage the provided research and data to highlight potential downsides and counter bullish arguments effectively.

Key points to focus on:

- Risks and Challenges: Highlight factors like market saturation, financial instability, bearish regime signals, elevated risk condition, or macroeconomic threats that could hinder the asset's performance.
- Competitive Weaknesses: Emphasize vulnerabilities such as weaker market positioning, declining adoption, or threats from competitors.
- Negative Indicators: Use evidence from the regime detector, market trends, or recent adverse news to support your position.
- Bull Counterpoints: Critically analyze the bull argument with specific data and sound reasoning, exposing weaknesses or over-optimistic assumptions.
- Engagement: Present your argument in a conversational style, directly engaging with the bull analyst's points and debating effectively rather than simply listing facts.

Resources available:

Market research report: {market_research_report}
Social media sentiment report: {sentiment_report}
Latest world affairs news: {news_report}
{fundamentals_label}: {fundamentals_report}{regime_section}
Conversation history of the debate: {history}
Last bull argument: {current_response}
Use this information to deliver a compelling bear argument, refute the bull's claims, and engage in a dynamic debate that demonstrates the risks and weaknesses of investing in the {target_label}.

After your argument, on its own line, write your confidence score in this exact format:
CONFIDENCE: <value between 0.00 and 1.00>
Where 1.00 = absolute conviction to avoid/sell, 0.50 = neutral/uncertain, 0.00 = no conviction.
""" + get_language_instruction()

        response = llm.invoke(prompt)
        raw_content = response.content

        # D — Adaptive Debate: parse confidence score (report §3.5)
        bear_confidence = _parse_confidence(raw_content)

        argument = f"Bear Analyst: {raw_content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bear_history": bear_history + "\n" + argument,
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
            "bear_confidence": bear_confidence,
            "bull_confidence": investment_debate_state.get("bull_confidence", 0.5),
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bear_node
