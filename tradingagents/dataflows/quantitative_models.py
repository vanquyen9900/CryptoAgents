import numpy as np
import pandas as pd
import tensorflow as tf
from typing import Annotated, Dict, Tuple

from .stockstats_utils import load_ohlcv


REGIME_LABELS = ("Bear", "Sideway", "Bull")


def _rolling_slope(values: np.ndarray) -> float:
    if len(values) < 2 or values[0] == 0:
        return 0.0
    y = values / values[0] - 1.0
    x = np.arange(len(values), dtype=float)
    return float(np.polyfit(x, y, 1)[0])


def preprocess_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    """Create compact, cross-asset OHLCV features for regime detection."""
    data = df.copy().sort_values("Date").reset_index(drop=True)
    data["log_return_1d"] = np.log(data["Close"] / data["Close"].shift(1))
    data["log_return_5d"] = np.log(data["Close"] / data["Close"].shift(5))
    data["volatility_10d"] = data["log_return_1d"].rolling(10).std()
    data["volatility_20d"] = data["log_return_1d"].rolling(20).std()

    sma20 = data["Close"].rolling(20).mean()
    data["distance_sma20"] = data["Close"] / sma20 - 1.0
    data["drawdown_20d"] = data["Close"] / data["Close"].rolling(20).max() - 1.0
    data["range_pct"] = (data["High"] - data["Low"]) / data["Close"]

    volume_mean = data["Volume"].rolling(20).mean()
    volume_std = data["Volume"].rolling(20).std().replace(0, np.nan)
    data["volume_zscore"] = (data["Volume"] - volume_mean) / volume_std
    data["trend_slope_20d"] = data["Close"].rolling(20).apply(_rolling_slope, raw=True)

    feature_cols = [
        "log_return_1d",
        "log_return_5d",
        "volatility_10d",
        "volatility_20d",
        "trend_slope_20d",
        "distance_sma20",
        "drawdown_20d",
        "volume_zscore",
        "range_pct",
    ]
    return data.dropna(subset=feature_cols).reset_index(drop=True)


def _standardize_features(frame: pd.DataFrame) -> Tuple[tf.Tensor, Dict[str, float]]:
    cols = [
        "log_return_1d",
        "log_return_5d",
        "volatility_20d",
        "trend_slope_20d",
        "distance_sma20",
        "volume_zscore",
        "range_pct",
    ]
    raw = tf.constant(frame[cols].to_numpy(dtype=np.float32), dtype=tf.float32)
    mean, var = tf.nn.moments(raw, axes=[0])
    std = tf.maximum(tf.sqrt(var), tf.constant(1e-6, dtype=tf.float32))
    standardized = tf.clip_by_value((raw - mean) / std, -5.0, 5.0)
    return standardized, {"rows": float(raw.shape[0]), "features": float(raw.shape[1])}


def _log_gaussian_diag(x: tf.Tensor, means: tf.Tensor, variances: tf.Tensor) -> tf.Tensor:
    x_expanded = x[:, None, :]
    var = tf.maximum(variances[None, :, :], 1e-5)
    diff = x_expanded - means[None, :, :]
    log_det = tf.reduce_sum(tf.math.log(var), axis=-1)
    quad = tf.reduce_sum(tf.square(diff) / var, axis=-1)
    dim = tf.cast(tf.shape(x)[1], tf.float32)
    return -0.5 * (dim * tf.math.log(2.0 * np.pi) + log_det + quad)


def _forward_backward(
    log_emissions: tf.Tensor,
    init_probs: tf.Tensor,
    transition: tf.Tensor,
) -> Tuple[tf.Tensor, tf.Tensor, tf.Tensor]:
    tiny = tf.constant(1e-8, dtype=tf.float32)
    log_init = tf.math.log(tf.maximum(init_probs, tiny))
    log_trans = tf.math.log(tf.maximum(transition, tiny))
    time_steps = int(log_emissions.shape[0])

    alphas = [log_init + log_emissions[0]]
    for t in range(1, time_steps):
        prev = alphas[-1]
        alpha_t = log_emissions[t] + tf.reduce_logsumexp(prev[:, None] + log_trans, axis=0)
        alphas.append(alpha_t)
    log_alpha = tf.stack(alphas, axis=0)
    log_likelihood = tf.reduce_logsumexp(log_alpha[-1])

    betas = [None] * time_steps
    betas[-1] = tf.zeros_like(log_emissions[-1])
    for t in range(time_steps - 2, -1, -1):
        beta_t = tf.reduce_logsumexp(
            log_trans + log_emissions[t + 1][None, :] + betas[t + 1][None, :],
            axis=1,
        )
        betas[t] = beta_t
    log_beta = tf.stack(betas, axis=0)

    gamma = tf.nn.softmax(log_alpha + log_beta, axis=1)

    xis = []
    for t in range(time_steps - 1):
        log_xi = (
            log_alpha[t][:, None]
            + log_trans
            + log_emissions[t + 1][None, :]
            + log_beta[t + 1][None, :]
        )
        log_xi -= tf.reduce_logsumexp(log_xi)
        xis.append(tf.exp(log_xi))
    xi = tf.stack(xis, axis=0) if xis else tf.zeros((0, 3, 3), dtype=tf.float32)
    return gamma, xi, log_likelihood


def _fit_gaussian_hmm(features: tf.Tensor, num_states: int = 3, iterations: int = 8):
    """Fit a small diagonal-Gaussian HMM with TensorFlow EM steps."""
    n = int(features.shape[0])
    if n < 25:
        raise ValueError("Need at least 25 feature rows for HMM regime detection")

    direction_score = features[:, 1] + features[:, 3] + 0.5 * features[:, 4]
    ordered = tf.argsort(direction_score)
    init_idx = tf.stack([ordered[0], ordered[n // 2], ordered[-1]])
    means = tf.gather(features, init_idx)

    _, global_var = tf.nn.moments(features, axes=[0])
    variances = tf.tile(tf.maximum(global_var[None, :], 1e-3), [num_states, 1])
    init_probs = tf.ones([num_states], dtype=tf.float32) / float(num_states)
    transition = tf.eye(num_states, dtype=tf.float32) * 0.86
    transition += (tf.ones([num_states, num_states], dtype=tf.float32) - tf.eye(num_states, dtype=tf.float32)) * (0.14 / (num_states - 1))

    gamma = None
    for _ in range(iterations):
        log_emissions = _log_gaussian_diag(features, means, variances)
        gamma, xi, _ = _forward_backward(log_emissions, init_probs, transition)

        gamma_sum = tf.maximum(tf.reduce_sum(gamma, axis=0), 1e-6)
        init_probs = tf.maximum(gamma[0], 1e-6)
        init_probs = init_probs / tf.reduce_sum(init_probs)

        trans_counts = tf.reduce_sum(xi, axis=0)
        transition = trans_counts / tf.maximum(tf.reduce_sum(trans_counts, axis=1, keepdims=True), 1e-6)
        transition = 0.02 / num_states + 0.98 * transition
        transition = transition / tf.reduce_sum(transition, axis=1, keepdims=True)

        means = tf.matmul(gamma, features, transpose_a=True) / gamma_sum[:, None]
        centered = features[:, None, :] - means[None, :, :]
        variances = tf.reduce_sum(gamma[:, :, None] * tf.square(centered), axis=0) / gamma_sum[:, None]
        variances = tf.maximum(variances, 1e-4)

    log_emissions = _log_gaussian_diag(features, means, variances)
    gamma, _, log_likelihood = _forward_backward(log_emissions, init_probs, transition)
    states = tf.argmax(gamma, axis=1).numpy()
    return states, gamma.numpy(), means.numpy(), transition.numpy(), float(log_likelihood.numpy())


def _map_states_to_regimes(frame: pd.DataFrame, states: np.ndarray) -> Dict[int, str]:
    stats = []
    for state in sorted(set(states.tolist())):
        subset = frame.iloc[np.where(states == state)[0]]
        directional = (
            subset["log_return_5d"].mean()
            + subset["trend_slope_20d"].mean()
            + 0.5 * subset["distance_sma20"].mean()
        )
        stats.append((state, float(directional)))

    ordered = [state for state, _ in sorted(stats, key=lambda item: item[1])]
    mapping = {}
    if ordered:
        mapping[ordered[0]] = "Bear"
        mapping[ordered[-1]] = "Bull"
        for state in ordered[1:-1]:
            mapping[state] = "Sideway"
    return mapping


def _percentile_rank(series: pd.Series, value: float) -> float:
    clean = series.dropna().to_numpy(dtype=float)
    if len(clean) == 0:
        return 0.0
    return float(np.mean(clean <= value))


def run_market_regime_detection(symbol: str, curr_date: str, look_back_days: int = 60) -> dict:
    history_days = max(120, look_back_days * 2)
    raw_df = load_ohlcv(symbol, curr_date).tail(history_days).reset_index(drop=True)
    if len(raw_df) < 45:
        return {"status": "error", "message": f"Insufficient OHLCV history ({len(raw_df)} rows)."}

    frame = preprocess_regime_features(raw_df)
    if len(frame) < 25:
        return {"status": "error", "message": "Insufficient rows after feature engineering."}

    features, feature_meta = _standardize_features(frame)
    states, posterior, means, transition, log_likelihood = _fit_gaussian_hmm(features)
    state_labels = _map_states_to_regimes(frame, states)

    last_window = states[-5:] if len(states) >= 5 else states
    counts = np.bincount(last_window, minlength=3)
    current_state = int(np.argmax(counts))
    current_regime = state_labels.get(current_state, "Sideway")
    confidence = float(np.mean(posterior[-len(last_window):, current_state]))

    latest = frame.iloc[-1]
    vol_pct = _percentile_rank(frame["volatility_20d"], float(latest["volatility_20d"]))
    range_pct = _percentile_rank(frame["range_pct"], float(latest["range_pct"]))
    drawdown = float(latest["drawdown_20d"])
    risk_score = float(np.clip(0.45 * vol_pct + 0.25 * range_pct + 0.30 * min(abs(drawdown) / 0.12, 1.0), 0.0, 1.0))

    if risk_score >= 0.80:
        risk_condition = "Stress"
    elif risk_score >= 0.65:
        risk_condition = "High Risk"
    elif risk_score >= 0.40:
        risk_condition = "Normal Risk"
    else:
        risk_condition = "Low Risk"

    state_summary = []
    for state in sorted(set(states.tolist())):
        subset = frame.iloc[np.where(states == state)[0]]
        state_summary.append({
            "state": int(state),
            "label": state_labels.get(int(state), "Sideway"),
            "days": int(len(subset)),
            "mean_return_5d": float(subset["log_return_5d"].mean()),
            "mean_volatility_20d": float(subset["volatility_20d"].mean()),
            "mean_trend_slope_20d": float(subset["trend_slope_20d"].mean()),
        })

    return {
        "status": "success",
        "symbol": symbol,
        "analysis_date": curr_date,
        "history_rows": int(len(raw_df)),
        "feature_rows": int(feature_meta["rows"]),
        "current_state": current_state,
        "current_regime": current_regime,
        "confidence": confidence,
        "risk_condition": risk_condition,
        "risk_score": risk_score,
        "volatility_percentile": vol_pct,
        "range_percentile": range_pct,
        "drawdown_20d": drawdown,
        "return_5d": float(latest["log_return_5d"]),
        "distance_sma20": float(latest["distance_sma20"]),
        "volume_zscore": float(latest["volume_zscore"]),
        "recent_states": [state_labels.get(int(s), "Sideway") for s in last_window.tolist()],
        "state_summary": state_summary,
        "transition_matrix": transition.tolist(),
        "log_likelihood": log_likelihood,
    }


def _format_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def get_market_regime(
    symbol: Annotated[str, "Ticker symbol, e.g. BTC-USD, ETH-USD, AAPL"],
    curr_date: Annotated[str, "The current trading date, YYYY-MM-DD"],
    look_back_days: Annotated[int, "How many historical days to include before doubling to the HMM window"] = 60,
) -> str:
    """Detect the current Bull/Bear/Sideway regime with a TensorFlow Gaussian HMM."""
    res = run_market_regime_detection(symbol, curr_date, look_back_days=look_back_days)
    header = f"### [TensorFlow HMM Market Regime Report for {symbol.upper()}]\n"
    header += f"Analysis Date: {curr_date}\n\n"

    if res["status"] != "success":
        return header + f"Error: {res['message']}"

    table = "| Metric | Value |\n| --- | --- |\n"
    table += f"| Current Regime | **{res['current_regime']}** |\n"
    table += f"| Regime Confidence | {res['confidence'] * 100:.1f}% |\n"
    table += f"| Risk Condition | {res['risk_condition']} |\n"
    table += f"| Risk Score | {res['risk_score']:.2f} |\n"
    table += f"| Volatility Percentile | {res['volatility_percentile'] * 100:.1f}% |\n"
    table += f"| Intraday Range Percentile | {res['range_percentile'] * 100:.1f}% |\n"
    table += f"| 20D Drawdown | {_format_pct(res['drawdown_20d'])} |\n"
    table += f"| 5D Return | {_format_pct(res['return_5d'])} |\n"
    table += f"| Distance From SMA20 | {_format_pct(res['distance_sma20'])} |\n"
    table += f"| Volume Z-Score | {res['volume_zscore']:.2f} |\n"
    table += f"| Recent 5-Day Regimes | {', '.join(res['recent_states'])} |\n"
    table += f"| OHLCV Rows Used | {res['history_rows']} raw / {res['feature_rows']} feature rows |\n"

    state_rows = "\n| HMM State | Label | Days | Mean 5D Return | Mean 20D Vol | Mean Trend Slope |\n| --- | --- | ---: | ---: | ---: | ---: |\n"
    for item in res["state_summary"]:
        state_rows += (
            f"| {item['state']} | {item['label']} | {item['days']} | "
            f"{_format_pct(item['mean_return_5d'])} | "
            f"{_format_pct(item['mean_volatility_20d'])} | "
            f"{item['mean_trend_slope_20d']:.5f} |\n"
        )

    explanation = (
        "\n**Interpretation**:\n"
        "This is a TensorFlow-based Gaussian HMM regime detector. It does not predict future price. "
        "It fits three hidden states on recent normalized OHLCV features, then maps those states to "
        "Bull, Bear, or Sideway using each state's realized return and trend characteristics. "
        "Use the regime as market context for research debate and risk sizing, not as a standalone trade signal."
    )
    return header + table + state_rows + explanation
