# TradingAgents/graph/conditional_logic.py

import logging

from tradingagents.agents.utils.agent_states import AgentState

logger = logging.getLogger(__name__)


class ConditionalLogic:
    """Handles conditional logic for determining graph flow."""

    def __init__(
        self,
        max_debate_rounds=1,
        max_risk_discuss_rounds=1,
        # D — Adaptive Debate params (report §3.5)
        adaptive_debate_theta: float = 0.75,
        adaptive_debate_k_max: int = 3,
    ):
        """Initialize with configuration parameters.

        Args:
            max_debate_rounds:        Legacy fixed-round cap (used only when
                                      adaptive debate is disabled).
            max_risk_discuss_rounds:  Round cap for the risk debate phase.
            adaptive_debate_theta:    Consensus threshold θ ∈ (0, 1].
                                      Debate stops when S_k ≥ θ.
                                      Default 0.75 per report §3.5.
            adaptive_debate_k_max:   Hard ceiling on debate rounds.
                                      Default 3 per report §3.5.
        """
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds
        self.adaptive_debate_theta = adaptive_debate_theta
        self.adaptive_debate_k_max = adaptive_debate_k_max

    # ── Analyst continue/stop helpers (unchanged) ──────────────

    def should_continue_market(self, state: AgentState):
        """Determine if market analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_market"
        return "Msg Clear Market"

    def should_continue_social(self, state: AgentState):
        """Determine if sentiment-analyst tool round should continue.

        Method name keeps the legacy ``social`` suffix to match the
        ``AnalystType.SOCIAL = "social"`` wire value (saved-config
        back-compat); the returned ``clear_node`` label uses the v0.2.5
        rename so it matches the node registered by the execution plan.
        """
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_social"
        return "Msg Clear Sentiment"

    def should_continue_news(self, state: AgentState):
        """Determine if news analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_news"
        return "Msg Clear News"

    def should_continue_fundamentals(self, state: AgentState):
        """Determine if fundamentals analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_fundamentals"
        return "Msg Clear Fundamentals"

    def should_continue_quantitative(self, state: AgentState):
        """Determine if regime analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_quantitative"
        return "Msg Clear Regime"

    # ── Adaptive Debate (D — report §3.5) ─────────────────────

    def should_continue_debate(self, state: AgentState) -> str:
        """Adaptive stopping criterion for the investment debate.

        Algorithm (report §3.5):
          S_k = 1 − |C_bull − C_bear|
          Stop at the first round k* where S_k ≥ θ  OR  count ≥ 2 × K_max.

        A pair of confidence scores is available only after each side has
        spoken at least once (count ≥ 2).  Before that we fall back to the
        legacy alternation logic so the first exchange always happens.

        Fallback: if confidence scores are missing (e.g. old serialised state
        without the new fields), we revert to legacy fixed-round behaviour so
        existing tests and checkpoints are not broken.
        """
        ds = state["investment_debate_state"]
        count = ds["count"]
        hard_cap = 2 * self.adaptive_debate_k_max  # total turns = 2 per round

        # ── Hard cap (always respected) ────────────────────────
        if count >= hard_cap:
            logger.debug(
                "Debate stopped: hard cap reached (count=%d, cap=%d)", count, hard_cap
            )
            return "Research Manager"

        # ── Consensus check (needs at least one full exchange) ─
        if count >= 2:
            c_bull = ds.get("bull_confidence", 0.5)
            c_bear = ds.get("bear_confidence", 0.5)
            s_k = 1.0 - abs(c_bull - c_bear)
            logger.debug(
                "Debate round count=%d: C_bull=%.2f C_bear=%.2f S_k=%.2f theta=%.2f",
                count, c_bull, c_bear, s_k, self.adaptive_debate_theta,
            )
            if s_k >= self.adaptive_debate_theta:
                logger.debug("Debate stopped: consensus reached (S_k=%.2f >= θ=%.2f)", s_k, self.adaptive_debate_theta)
                return "Research Manager"

        # ── Continue: alternate speakers ───────────────────────
        if ds["current_response"].startswith("Bull"):
            return "Bear Researcher"
        return "Bull Researcher"

    # ── Risk debate (unchanged) ────────────────────────────────

    def should_continue_risk_analysis(self, state: AgentState) -> str:
        """Determine if risk analysis should continue."""
        if (
            state["risk_debate_state"]["count"] >= 3 * self.max_risk_discuss_rounds
        ):  # 3 rounds of back-and-forth between 3 agents
            return "Portfolio Manager"
        if state["risk_debate_state"]["latest_speaker"].startswith("Aggressive"):
            return "Conservative Analyst"
        if state["risk_debate_state"]["latest_speaker"].startswith("Conservative"):
            return "Neutral Analyst"
        return "Aggressive Analyst"
