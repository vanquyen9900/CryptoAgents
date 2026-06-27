import os
import json
import argparse
import logging
from datetime import datetime
from collections import defaultdict
from pathlib import Path
import pandas as pd
import numpy as np

DEFAULT_TEST_DATA_DIR = Path(__file__).resolve().parents[1] / "data_test_2024_q1"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def calculate_metrics(daily_nav, n_trading_days=252):
    """Calculate portfolio metrics based on daily NAV."""
    if len(daily_nav) == 0:
        return {"cr_pct": None, "arr_pct": None, "sharpe": None, "mdd_pct": None}

    start_nav = daily_nav.iloc[0]
    end_nav = daily_nav.iloc[-1]

    # Cumulative Return
    cr = (end_nav / start_nav) - 1.0

    # Annualized Return (assuming 252 trading days per year)
    days_in_period = len(daily_nav)
    if days_in_period > 0:
        arr = ((end_nav / start_nav) ** (n_trading_days / days_in_period)) - 1.0
    else:
        arr = 0.0

    # Daily returns for Sharpe Ratio
    daily_returns = daily_nav.pct_change().dropna()
    mean_return = daily_returns.mean()
    std_return = daily_returns.std()

    if pd.isna(std_return) or std_return == 0:
        sr = None
    else:
        sr = (mean_return / std_return) * np.sqrt(n_trading_days)

    # Max Drawdown
    roll_max = daily_nav.cummax()
    drawdown = daily_nav / roll_max - 1.0
    mdd = drawdown.min()

    return {
        "cr_pct": cr * 100,
        "arr_pct": arr * 100,
        "sharpe": sr,
        "mdd_pct": mdd * 100
    }

def run_backtest(df_price, df_signals, initial_capital=100000.0, transaction_cost_bps=0.0):
    """
    Simulate portfolio with 'next_open' execution.
    Signals are generated at day t, executed at day t+1 open.
    """
    df_price = df_price.sort_values("known_time").copy()

    # Ensure signals are matched by analysis_date (which corresponds to known_time of price)
    # df_signals has columns: ['analysis_date', 'action'] (action is 1.0 for BUY, 0.0 for SELL, etc.)
    df_merged = pd.merge(df_price, df_signals, left_on='known_time', right_on='analysis_date', how='left')

    # Forward fill target exposure. If HOLD, it keeps previous.
    # Initial exposure is 0.0
    df_merged['target_exposure'] = df_merged['action'].ffill().fillna(0.0)

    # Shift target exposure to t+1 because decision at t is executed at t+1 open
    df_merged['executed_exposure'] = df_merged['target_exposure'].shift(1).fillna(0.0)

    cash = initial_capital
    shares = 0.0

    equity_curve = []
    trade_logs = []

    for i in range(len(df_merged)):
        row = df_merged.iloc[i]
        date = row['known_time']
        open_price = row['open']
        close_price = row['close']
        target_exp = row['executed_exposure']

        # Calculate current portfolio value at OPEN to execute trades
        current_val_open = cash + shares * open_price
        target_value = current_val_open * target_exp

        # Determine shares needed
        target_shares = target_value / open_price if open_price > 0 else 0
        delta_shares = target_shares - shares

        if delta_shares != 0:
            trade_value = abs(delta_shares) * open_price
            cost = trade_value * (transaction_cost_bps / 10000.0)

            cash -= (delta_shares * open_price + cost)
            shares = target_shares

            trade_logs.append({
                "date": str(date)[:10],
                "action": "BUY" if delta_shares > 0 else "SELL",
                "shares": delta_shares,
                "price": open_price,
                "cost": cost
            })

        # End of day mark to market
        nav = cash + shares * close_price
        equity_curve.append({
            "date": str(date)[:10],
            "nav": nav,
            "cash": cash,
            "shares": shares,
            "close": close_price
        })

    df_equity = pd.DataFrame(equity_curve)
    if not df_equity.empty:
        df_equity['date'] = pd.to_datetime(df_equity['date'])
        df_equity = df_equity.set_index('date')

    return df_equity, trade_logs

def parse_action(action_str):
    action_str = str(action_str).strip().upper()
    if action_str in ["BUY", "OVERWEIGHT", "LONG"]:
        return 1.0
    elif action_str in ["SELL", "UNDERWEIGHT", "SHORT"]:
        # Only long-only for now according to typical setups, so SELL means 0 exposure
        return 0.0
    elif action_str in ["HOLD", "NEUTRAL"]:
        return np.nan # Use forward fill for HOLD
    else:
        logging.warning(f"Unparsed action: {action_str}, defaulting to HOLD")
        return np.nan

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tournament-id", required=True)
    parser.add_argument("--comparison-group", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--include-buy-and-hold", action="store_true")
    parser.add_argument("--execution", default="next_open", choices=["next_open"])
    parser.add_argument("--transaction-cost-bps", type=float, default=0.0)
    parser.add_argument("--data-dir", default=str(DEFAULT_TEST_DATA_DIR))
    args = parser.parse_args()

    # Load trajectories
    traj_path = os.path.join(args.data_dir, "memo_adaptation", "trajectories", "workflow_trajectories.jsonl")
    if not os.path.exists(traj_path):
        # Fallback to normal trajectories if needed
        traj_path = os.path.join(args.data_dir, "trajectories", "workflow_trajectories.jsonl")

    if not os.path.exists(traj_path):
        logging.error(f"Trajectories file not found at {traj_path}")
        return

    trajectories = []
    with open(traj_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            t = json.loads(line.strip())
            if t.get("tournament_id") == args.tournament_id and t.get("comparison_group") == args.comparison_group:
                # Extract date from analysis_time
                date_str = str(t.get("analysis_time"))[:10]
                if args.start_date <= date_str <= args.end_date and t.get("symbol") in args.symbols:
                    trajectories.append(t)

    logging.info(f"Loaded {len(trajectories)} trajectories for {args.comparison_group}")

    # Organize signals: symbol -> prompt_set -> date -> action
    signals = defaultdict(lambda: defaultdict(list))
    for t in trajectories:
        sym = t["symbol"]
        ps = t["prompt_set_id"]
        date_str = str(t["analysis_time"])[:10]
        decision = t.get("agent_outputs", {}).get("final_trade_decision", "HOLD")

        signals[sym][ps].append({
            "analysis_date": pd.to_datetime(date_str),
            "action": parse_action(decision)
        })

    # Load Price Daily
    price_path = os.path.join(args.data_dir, "normalized", "price_daily")
    if not os.path.exists(price_path):
        logging.error(f"Price data not found at {price_path}")
        return

    df_all_price = pd.read_parquet(price_path)
    df_all_price['known_time'] = pd.to_datetime(df_all_price['known_time'].astype(str).str[:10])

    # Filter price by eval window plus a few days for next_open execution
    df_eval_price = df_all_price[
        (df_all_price['known_time'] >= pd.to_datetime(args.start_date)) &
        (df_all_price['known_time'] <= pd.to_datetime(args.end_date) + pd.Timedelta(days=5))
    ].copy()

    output_dir = os.path.join(args.data_dir, "memo_adaptation", "portfolio_evaluation", args.comparison_group)
    os.makedirs(output_dir, exist_ok=True)

    metrics_records = []
    all_equity_curves = []

    # Evaluate strategies
    for sym in args.symbols:
        df_sym_price = df_eval_price[df_eval_price['instrument_id'] == sym].copy()

        # Evaluate B&H if requested
        if args.include_buy_and_hold:
            df_bh_signals = pd.DataFrame([{"analysis_date": df_sym_price['known_time'].min(), "action": 1.0}])
            df_bh_equity, bh_trades = run_backtest(df_sym_price, df_bh_signals, transaction_cost_bps=args.transaction_cost_bps)
            bh_metrics = calculate_metrics(df_bh_equity['nav'])

            metrics_records.append({
                "Category": "Market",
                "Model": "B&H",
                "Symbol": sym,
                "Prompt_Set": "N/A",
                **bh_metrics
            })

            # Save B&H equity curve
            for date, row in df_bh_equity.iterrows():
                all_equity_curves.append({
                    "symbol": sym,
                    "model": "B&H",
                    "date": str(date)[:10],
                    "nav": row['nav']
                })

        # Evaluate Agent Prompts
        for ps, sig_list in signals[sym].items():
            df_sig = pd.DataFrame(sig_list).sort_values("analysis_date")
            df_equity, trades = run_backtest(df_sym_price, df_sig, transaction_cost_bps=args.transaction_cost_bps)
            metrics = calculate_metrics(df_equity['nav'])

            metrics_records.append({
                "Category": "Ours",
                "Model": args.comparison_group,
                "Symbol": sym,
                "Prompt_Set": ps,
                **metrics
            })

            # Save equity curve
            for date, row in df_equity.iterrows():
                all_equity_curves.append({
                    "symbol": sym,
                    "model": args.comparison_group,
                    "prompt_set": ps,
                    "date": str(date)[:10],
                    "nav": row['nav']
                })

    # Save results
    df_metrics = pd.DataFrame(metrics_records)
    metrics_file = os.path.join(output_dir, "portfolio_metrics.jsonl")
    df_metrics.to_json(metrics_file, orient='records', lines=True)

    curves_file = os.path.join(output_dir, "equity_curves.jsonl")
    with open(curves_file, "w", encoding="utf-8") as f:
        for c in all_equity_curves:
            f.write(json.dumps(c) + "\n")

    # Markdown report
    report_file = os.path.join(output_dir, "summary_report.md")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(f"# Portfolio Evaluation: {args.comparison_group}\n\n")
        try:
            f.write(df_metrics.to_markdown(index=False))
        except ImportError:
            f.write("```text\n")
            f.write(df_metrics.to_string(index=False))
            f.write("\n```\n")

    logging.info(f"Evaluation complete. Saved to {output_dir}")

if __name__ == "__main__":
    main()
