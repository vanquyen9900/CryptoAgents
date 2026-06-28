"""Regime Analyst for market-state detection with TensorFlow HMM."""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_language_instruction,
)
from tradingagents.agents.utils.quantitative_analysis_tools import get_market_regime


def create_regime_analyst(llm):
    """Create a Regime Analyst node that reports current Bull/Bear/Sideway context."""

    def regime_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        asset_type = state.get("asset_type", "stock")
        instrument_context = build_instrument_context(ticker, asset_type)

        tools = [get_market_regime]

        system_message = (
            f"You are a Regime Analyst. Your task is to identify the current market regime for {ticker} "
            f"as of {current_date} using the TensorFlow HMM market-regime tool.\n\n"
            "You have access to one tool:\n"
            "- get_market_regime(symbol, curr_date, look_back_days): fits a 3-state Gaussian HMM on recent "
            "normalized OHLCV features and maps the current hidden state to Bull, Bear, or Sideway. "
            "It does not predict future price.\n\n"
            "Report requirements:\n"
            "1. Call get_market_regime first.\n"
            "2. Explain the current regime, confidence, and recent 5-day regime consistency.\n"
            "3. Explain whether the risk condition is low, normal, high, or stress.\n"
            "4. Give the research team concise implications: what evidence supports a bullish case, "
            "what evidence supports a bearish case, and what would make the regime unreliable.\n"
            "5. Do not fabricate model outputs; use only the tool result.\n"
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants. "
                    "Use the provided tools to progress towards answering the question. "
                    "You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = ""
        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "regime_report": report,
        }

    return regime_analyst_node


# Keep the old factory name as a compatibility alias for existing graph wiring/tests.
def create_quantitative_analyst(llm):
    return create_regime_analyst(llm)
