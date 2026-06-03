"""Quantitative & On-Chain Analyst for CryptoAgents.

Replaces the stock-specific ``fundamentals_analyst`` for crypto assets.
This agent is equipped with TensorFlow-powered deep learning tools:

  1. ``get_anomaly_signals``  — Autoencoder-based anomaly detection on
                                OHLCV price/volume sequences.
  2. ``get_trend_predictions`` — LSTM/GRU sequence classifier that forecasts
                                 short-term price direction (UP/HOLD/DOWN).

The agent synthesises the model outputs together with on-chain/macro context
to produce a quantitative analysis report for the research team.
"""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_language_instruction,
)
from tradingagents.agents.utils.quantitative_analysis_tools import (
    get_anomaly_signals,
    get_trend_predictions,
)


def create_quantitative_analyst(llm):
    """Create a Quantitative & On-Chain analyst node for the crypto trading graph."""

    def quantitative_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        asset_type = state.get("asset_type", "crypto")
        instrument_context = build_instrument_context(ticker, asset_type)

        tools = [
            get_anomaly_signals,
            get_trend_predictions,
        ]

        system_message = (
            f"You are a Quantitative & On-Chain Analyst specialising in the cryptocurrency market. "
            f"Your task is to produce a rigorous quantitative analysis report for {ticker} as of {current_date}.\n\n"
            "You have access to two TensorFlow deep-learning tools:\n"
            "  • **get_anomaly_signals(symbol, curr_date, look_back_days)** — runs an unsupervised "
            "Autoencoder on the historical OHLCV sequence and flags any abnormal price or volume behaviour "
            "(flash crashes, pump-and-dump patterns, liquidation cascades). The tool returns a reconstruction "
            "error score compared against a dynamic 95th-percentile threshold.\n"
            "  • **get_trend_predictions(symbol, curr_date, look_back_days)** — runs an LSTM classifier "
            "trained on lagged return, volatility, and volume momentum features to forecast the short-term "
            "directional bias (UP / HOLD / DOWN) with confidence probabilities for the next 3 periods.\n\n"
            "## How to use these tools\n"
            "1. Call **get_anomaly_signals** first to determine the current market health. "
            "If an anomaly is flagged, highlight the risk prominently and advise caution on position sizing.\n"
            "2. Call **get_trend_predictions** to retrieve the directional forecast and confidence levels. "
            "Cross-reference the forecast with the anomaly status — a HIGH-confidence UP forecast during "
            "an anomaly window is a contrarian signal worth flagging.\n"
            "3. Combine the model outputs with your own knowledge of:\n"
            "   - Crypto market regimes (BTC dominance, altcoin season, funding rates, liquidation heatmaps)\n"
            "   - Macro-liquidity environment (Fed policy, DXY, risk-on/risk-off)\n"
            "   - Protocol-level catalysts (upgrades, halving events, regulatory news)\n\n"
            "## Report structure\n"
            "Write a comprehensive quantitative analysis covering:\n"
            "1. **Anomaly status** — is the market exhibiting abnormal behaviour? Cite the anomaly score vs threshold.\n"
            "2. **Short-term trend forecast** — directional prediction, confidence %, and what it implies for entry timing.\n"
            "3. **Quantitative risk assessment** — expected volatility, suggested stop-loss range based on ATR-equivalent, "
            "position-sizing guidance under current anomaly conditions.\n"
            "4. **Macro & on-chain context** — any regime-level factors that amplify or contradict the model outputs.\n"
            "5. **Summary table** — a Markdown table consolidating key quantitative signals, their direction, "
            "confidence, and recommended action.\n\n"
            "Provide specific, actionable insights. Do NOT fabricate model outputs — use the tools."
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
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
            "quantitative_report": report,
        }

    return quantitative_analyst_node
