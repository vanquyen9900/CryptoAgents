### 🗂️ Toàn bộ Dữ liệu Bộ nhớ (Memory Bank)

Để minh bạch hóa quá trình ra quyết định của Agent ở Arm B, dưới đây là **toàn bộ 13 bài học** hiện có trong tệp `memo_memory_bank.jsonl`. Bộ nhớ được chia làm 2 phần: Bài học mồi từ 2022 và Bài học tích lũy hàng tuần trong Q1/2024.

#### A. Nhóm Bài học mồi từ chu kỳ 2022 (Seed Memories)
Các bài học này được nạp vào mô hình trước khi chạy Q1/2024, đúc kết từ môi trường Bear Market để dạy Agent cách phòng thủ:

**1. Bearish Trend Following Underweight (bearish_momentum)**
- **Nhận định (Summary)**: AMZN is in a bearish momentum state with price below both SMA50 and SMA200, MACD negative, and a 15-row return of -7.4%. RSI is neutral, so the stock is not yet deeply oversold; this is more of a trend-confirmation setup than a rebound setup.
- **Hành động (DO)**:
  - Underweight or stay defensive when price is below both SMA50 and SMA200.
  - Treat negative MACD plus a recent multi-day decline as trend confirmation, not a dip-buy signal.
  - Wait for price to reclaim at least SMA50 with improving momentum before adding risk.
  - Use elevated volume on a down session as confirmation of active selling pressure.
- **Cần tránh (AVOID)**:
  - Do not Buy solely because RSI is neutral or because the stock is below a prior support area.
  - Do not overweight positive broker commentary when price action and momentum are deteriorating.
  - Do not assume a one-day bounce indicates trend reversal after a multi-week decline.
  - Do not average down into a below-SMA50/below-SMA200, negative-MACD regime.

**2. Regime-Sensitive Hold Bias (bearish_momentum)**
- **Nhận định (Summary)**: AMZN is in a bearish momentum regime: price is below both SMA50 and SMA200, RSI is weak, MACD is negative, and recent returns are down. In this state, the default edge is to avoid new longs unless there is a clear reversal catalyst. The observed winner/loser split shows that prompt sets can diverge between Hold and Buy, but the buy attempt under this setup lost on the weighted 1d/5d/20d reward horizon.
- **Hành động (DO)**:
  - Default to Hold when price is below both SMA50 and SMA200 and MACD is negative.
  - Require a confirmed reversal before taking a long: reclaim SMA50, improving RSI, and MACD cross/inflection.
  - Use the 20d horizon as the primary filter; if longer-horizon trend remains negative, avoid contrarian buys.
- **Cần tránh (AVOID)**:
  - Do not Buy solely because the stock is oversold or because there are mixed/supportive headlines.
  - Do not interpret moderate volume as a bullish breakout by itself.
  - Do not average into weakness while the trend stack remains bearish.

**3. Risk Off Trend Following (bearish_momentum)**
- **Nhận định (Summary)**: AMZN was in a high-conviction bearish momentum state: price below both SMA50 and SMA200, RSI weak, MACD negative, and the recent return was sharply down with elevated volume. This is a regime where the path of least resistance is still lower, so the prior trend dominates mixed fundamentals or short-term bounces.
- **Hành động (DO)**:
  - Underweight the position when price is below SMA50 and SMA200 and MACD is negative.
  - Require trend-reversal confirmation before upgrading to Buy, such as reclaiming SMA50 plus improving momentum.
  - Use elevated volume as confirmation of active selling unless price also breaks above resistance.
- **Cần tránh (AVOID)**:
  - Do not Buy solely because of short-term bounce or mixed supportive news.
  - Do not treat a one-day rebound as a regime change when RSI is still weak and MACD remains negative.
  - Do not override the trend with optimism from isolated analyst or business updates.

**4. Trend Continuation Short Bias (bearish_momentum)**
- **Nhận định (Summary)**: AMZN is in a high-conviction bearish momentum state: price is below both SMA50 and SMA200, RSI is weak, MACD is negative, and the recent return is sharply down on elevated volume. This is a regime where downside continuation is more actionable than mean reversion.
- **Hành động (DO)**:
  - Prefer Sell or reduce exposure when price is below both SMA50 and SMA200 and MACD is negative.
  - Use elevated volume on down days as confirmation that the bearish move is being accepted by the market.
  - Bias toward continuation over mean reversion in this exact regime, especially when the 20d horizon dominates scoring.
- **Cần tránh (AVOID)**:
  - Avoid Hold when all trend and momentum signals are aligned bearish.
  - Avoid waiting for positive news to rescue the trade if price action keeps weakening.
  - Avoid treating a weak RSI alone as an oversold bounce setup when the larger trend is still down.

**5. State-Specific Trade-Off (bullish_momentum)**
- **Nhận định (Summary)**: AMZN is in a fragile bullish-momentum transition: price is above SMA50 but still below SMA200, RSI is neutral, MACD is barely positive, and the recent 15-row return is still negative. This is a decision point where the market is bouncing inside a larger downtrend, so the edge depends on whether the model prioritizes trend continuation risk or the immediate reversal setup.
- **Hành động (DO)**:
  - Sell or trim when price is reclaiming only the short SMA but remains below the long SMA after a sharp recent decline.
  - Prefer exit/short-risk reduction if MACD is positive but close to zero and RSI is neutral, because momentum is not confirmed.
  - Use the bounce to de-risk when the prior trend was down and the rebound is not backed by strong momentum expansion.
- **Cần tránh (AVOID)**:
  - Avoid Hold when the move is just a relief bounce inside a broader bearish structure.
  - Avoid assuming a positive MACD alone means trend repair.
  - Avoid waiting for SMA200 recovery as the only confirmation if the recent drawdown is still dominant.

**6. Event Risk Momentum Split (bullish_momentum)**
- **Nhận định (Summary)**: AMZN was in a constructive momentum regime (above SMA50, below SMA200, RSI strong, MACD positive, return up) with unusually high volume, but it was also immediately before earnings. This is a classic high-variance inflection point where the same bullish technical setup can justify either Buy or Hold depending on whether the prompt prioritizes momentum continuation or event-risk avoidance.
- **Hành động (DO)**:
  - Buy when price is above SMA50, RSI is strong, MACD is positive, and volume confirms the move.
  - Treat pre-earnings momentum as tradable when the technical setup is aligned and the move is already underway.
  - Prefer participation over caution when the weighted scorer rewards 5d/20d continuation and there is no sign of technical exhaustion.
- **Cần tránh (AVOID)**:
  - Avoid automatic Hold just because an earnings announcement is imminent.
  - Avoid letting macro-defensive logic suppress a clean momentum signal without additional evidence of reversal or breakdown.
  - Avoid using SMA200 proximity as a reason to wait if the short-term trend is already confirmed and the trade horizon includes post-event continuation.

**7. Trajectory Reflection (bearish_momentum)**
- **Nhận định (Summary)**: AMZN was in a clear bearish momentum regime: price below both SMA50 and SMA200, RSI weak, MACD negative, and 15-row return down. This is a decisive inflection state because the same inputs produced opposite actions, and the weighted 1d/5d/20d scorer rewarded the path that caught a short-horizon continuation into a much larger 20d rebound.
- **Hành động (DO)**:
  - Treat the setup as a possible contrarian reversal candidate, not just a bearish trend-following setup.
  - Use a small Buy or starter long when the tape is weak but stretched and you are optimizing for 5d/20d reward.
  - Expect possible negative 1d noise and judge the trade on multi-day follow-through.
- **Cần tránh (AVOID)**:
  - Avoid automatic Underweight/flat decisions purely because price is below both moving averages.
  - Avoid overreacting to the negative MACD/RSI by assuming downside must continue immediately.
  - Avoid using this lesson for short-horizon scalps where 1d outcome dominates.

**8. Trajectory Reflection (bearish_momentum)**
- **Nhận định (Summary)**: AMZN is in a high-conviction bearish momentum state: price is below both SMA50 and SMA200, RSI is weak, MACD is negative, and the 15-session return is sharply down with elevated volume. This is a regime where trend-following pressure dominates and signals can diverge on whether to fade the move or respect the tape.
- **Hành động (DO)**:
  - Treat a deep selloff below SMA50 and SMA200 as a decisive momentum-break state.
  - Consider a small tactical Buy only if oversold conditions and reversal evidence appear together.
  - Use tight sizing and explicit risk limits when fading an extended decline.
- **Cần tránh (AVOID)**:
  - Avoid defaulting to Underweight just because the stock has fallen sharply.
  - Avoid assuming bearish momentum always implies further downside on the next 1d/5d/20d horizons.
  - Avoid scaling aggressively into the trend without a reversal catalyst.

#### B. Nhóm Bài học tích lũy hàng tuần (Q1/2024 Weekly Learning)
Các bài học này được Agent tự động tạo ra vào cuối mỗi tuần giao dịch trong Q1/2024 (phản tư - Reflection) để tối ưu hóa quyết định cho tuần tiếp theo:

**1. Tuần giao dịch: 2024-01-02 đến 2024-01-05**
- **Nhật ký (Reflection)**: Weekly Reflection (2024-01-02 to 2024-01-05): | Actions taken: {'AAPL: Hold': 8, 'GOOGL: Buy': 6, 'GOOGL: Underweight': 6, 'AMZN: Buy': 5, 'AMZN: Underweight': 4, 'AMZN: Hold': 3, 'AAPL: Buy': 2, 'AAPL: Underweight': 2} | Situational lesson: For setups resembling the week 2024-01-02 to 2024-01-05, compare the current technical/news evidence against the recent decision ledger before changing exposure. Avoid treating momentum alone as sufficient; require support/resistance, risk, and macro/social confirmation before increasing or reducing a position.

**2. Tuần giao dịch: 2024-01-08 đến 2024-01-12**
- **Nhật ký (Reflection)**: Weekly Reflection (2024-01-08 to 2024-01-12): | Actions taken: {'GOOGL: Buy': 8, 'AMZN: Underweight': 7, 'AMZN: Buy': 7, 'AAPL: Buy': 6, 'AAPL: Hold': 5, 'GOOGL: Underweight': 5, 'AAPL: Underweight': 4, 'GOOGL: Hold': 2, 'AMZN: Hold': 1} | Situational lesson: For setups resembling the week 2024-01-08 to 2024-01-12, compare the current technical/news evidence against the recent decision ledger before changing exposure. Avoid treating momentum alone as sufficient; require support/resistance, risk, and macro/social confirmation before increasing or reducing a position.

**3. Tuần giao dịch: 2024-01-15 đến 2024-01-19**
- **Nhật ký (Reflection)**: Weekly Reflection (2024-01-15 to 2024-01-19): | Actions taken: {'GOOGL: Buy': 6, 'GOOGL: Underweight': 6, 'AAPL: Underweight': 5, 'AAPL: Buy': 5, 'AMZN: Hold': 4, 'AMZN: Buy': 4, 'AMZN: Underweight': 4, 'AAPL: Hold': 2} | Situational lesson: For setups resembling the week 2024-01-15 to 2024-01-19, compare the current technical/news evidence against the recent decision ledger before changing exposure. Avoid treating momentum alone as sufficient; require support/resistance, risk, and macro/social confirmation before increasing or reducing a position.

**4. Tuần giao dịch: 2024-01-22 đến 2024-01-26**
- **Nhật ký (Reflection)**: Weekly Reflection (2024-01-22 to 2024-01-26): | Actions taken: {'AMZN: Hold': 8, 'GOOGL: Hold': 7, 'AAPL: Hold': 5, 'AAPL: Buy': 5, 'GOOGL: Underweight': 5, 'AAPL: Underweight': 4, 'AMZN: Buy': 4, 'AMZN: Underweight': 3, 'GOOGL: Buy': 3, 'AAPL: ': 1} | Situational lesson: For setups resembling the week 2024-01-22 to 2024-01-26, compare the current technical/news evidence against the recent decision ledger before changing exposure. Avoid treating momentum alone as sufficient; require support/resistance, risk, and macro/social confirmation before increasing or reducing a position.

**5. Tuần giao dịch: 2024-01-29 đến 2024-01-31**
- **Nhật ký (Reflection)**: Weekly Reflection (2024-01-29 to 2024-01-31): | Actions taken: {'AAPL: Hold': 7, 'AMZN: Hold': 6, 'GOOGL: Hold': 6, 'AMZN: Buy': 2, 'GOOGL: Underweight': 2, 'GOOGL: Buy': 1, 'AAPL: Underweight': 1, 'AMZN: Underweight': 1, 'AAPL: ': 1} | Situational lesson: For setups resembling the week 2024-01-29 to 2024-01-31, compare the current technical/news evidence against the recent decision ledger before changing exposure. Avoid treating momentum alone as sufficient; require support/resistance, risk, and macro/social confirmation before increasing or reducing a position.
