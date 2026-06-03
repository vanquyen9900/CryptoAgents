import numpy as np
import pandas as pd
import tensorflow as tf
from datetime import datetime
from typing import Annotated
from .stockstats_utils import load_ohlcv

# Set random seed for reproducibility
tf.random.set_seed(42)
np.random.seed(42)

def preprocess_features(df: pd.DataFrame) -> pd.DataFrame:
    """Preprocess raw OHLCV DataFrame into normalized features.
    
    Features computed:
    - Log returns (Close)
    - Volatility (High-Low relative to Close)
    - Volume Momentum (Volume relative to 10-day SMA)
    - Daily return volatility (std over 5-day window)
    """
    df = df.copy()
    
    # Calculate log returns
    df['log_ret'] = np.log(df['Close'] / df['Close'].shift(1))
    
    # Relative volatility
    df['hl_vol'] = (df['High'] - df['Low']) / df['Close']
    
    # Volume momentum
    vol_sma = df['Volume'].rolling(window=10).mean()
    df['vol_ratio'] = df['Volume'] / (vol_sma + 1e-8)
    
    # Rolling standard deviation of returns
    df['ret_std'] = df['log_ret'].rolling(window=5).std()
    
    # Drop rows with NaNs resulting from shifts and rolling calculations
    df = df.dropna().reset_index(drop=True)
    return df

def scale_features(features_df: pd.DataFrame) -> np.ndarray:
    """Scale feature columns to [0, 1] range using min-max scaling."""
    cols = ['log_ret', 'hl_vol', 'vol_ratio', 'ret_std']
    data = features_df[cols].values
    
    min_vals = np.min(data, axis=0)
    max_vals = np.max(data, axis=0)
    # Avoid division by zero
    range_vals = np.where(max_vals - min_vals == 0, 1e-8, max_vals - min_vals)
    
    scaled_data = (data - min_vals) / range_vals
    return scaled_data

def prepare_sequences(data: np.ndarray, window_size: int = 10):
    """Slice 2D array into 3D sequences of shape (samples, window_size, features)."""
    X = []
    for i in range(len(data) - window_size + 1):
        X.append(data[i:i + window_size])
    return np.array(X)

def build_autoencoder(window_size: int, feature_dim: int) -> tf.keras.Model:
    """Build a simple Dense-based Autoencoder for Anomaly Detection."""
    inputs = tf.keras.Input(shape=(window_size, feature_dim))
    
    # Flatten window sequences
    flat = tf.keras.layers.Flatten()(inputs)
    
    # Encoder
    encoded = tf.keras.layers.Dense(8, activation='relu')(flat)
    encoded = tf.keras.layers.Dense(4, activation='relu')(encoded)
    
    # Decoder
    decoded = tf.keras.layers.Dense(8, activation='relu')(encoded)
    flat_outputs = tf.keras.layers.Dense(window_size * feature_dim, activation='sigmoid')(decoded)
    
    # Reshape back to original dimensions
    outputs = tf.keras.layers.Reshape((window_size, feature_dim))(flat_outputs)
    
    model = tf.keras.Model(inputs, outputs)
    model.compile(optimizer='adam', loss='mse')
    return model

def build_trend_model(window_size: int, feature_dim: int) -> tf.keras.Model:
    """Build a sequence model (LSTM) for price trend classification."""
    inputs = tf.keras.Input(shape=(window_size, feature_dim))
    x = tf.keras.layers.LSTM(16, return_sequences=False)(inputs)
    x = tf.keras.layers.Dropout(0.2)(x)
    outputs = tf.keras.layers.Dense(3, activation='softmax')(x) # classes: [DOWN, HOLD, UP]
    
    model = tf.keras.Model(inputs, outputs)
    model.compile(optimizer='adam', loss='sparse_categorical_crossentropy', metrics=['accuracy'])
    return model

def run_anomaly_detection(symbol: str, curr_date: str, train_days: int = 180, window_size: int = 10) -> dict:
    """Train and run Autoencoder Anomaly Detection on the given symbol up to curr_date.
    
    Returns a dictionary with status, reconstruction error, threshold, and anomaly flag.
    """
    try:
        # Load raw data up to curr_date
        raw_df = load_ohlcv(symbol, curr_date)
        if len(raw_df) < train_days // 3:
            return {"status": "error", "message": f"Insufficient historical data ({len(raw_df)} rows)."}
        
        # Limit to the training window
        df_train = raw_df.tail(train_days).reset_index(drop=True)
        
        # Preprocess features
        features_df = preprocess_features(df_train)
        if len(features_df) <= window_size:
            return {"status": "error", "message": "Dataset too small after feature engineering."}
        
        # Scale features
        scaled_data = scale_features(features_df)
        
        # Prepare sequences
        X = prepare_sequences(scaled_data, window_size=window_size)
        
        # Train Autoencoder
        model = build_autoencoder(window_size, X.shape[2])
        model.fit(X, X, epochs=10, batch_size=16, verbose=0)
        
        # Evaluate reconstruction loss across history
        reconstructed = model.predict(X, verbose=0)
        mse = np.mean(np.square(X - reconstructed), axis=(1, 2))
        
        # Dynamic threshold (95th percentile of reconstruction loss)
        threshold = np.percentile(mse, 95)
        
        # Current status is the last sequence
        last_mse = mse[-1]
        is_anomaly = bool(last_mse > threshold)
        
        # Extract recent anomalous dates
        anomaly_indices = np.where(mse > threshold)[0]
        anomaly_dates = features_df['Date'].iloc[anomaly_indices + window_size - 1].dt.strftime('%Y-%m-%d').tolist()
        recent_anomalies = [d for d in anomaly_dates if d <= curr_date][-5:]
        
        return {
            "status": "success",
            "is_anomaly": is_anomaly,
            "anomaly_score": float(last_mse),
            "threshold": float(threshold),
            "recent_anomalies": recent_anomalies,
            "total_anomalies_detected": len(anomaly_dates)
        }
        
    except Exception as e:
        return {"status": "fallback", "message": str(e)}

def run_trend_forecasting(symbol: str, curr_date: str, train_days: int = 180, window_size: int = 10) -> dict:
    """Train and run Price Trend Forecasting on the given symbol up to curr_date.
    
    Returns a dictionary with status, predicted trend label, and class probabilities.
    """
    try:
        # Load raw data up to curr_date
        raw_df = load_ohlcv(symbol, curr_date)
        if len(raw_df) < train_days // 3:
            return {"status": "error", "message": f"Insufficient historical data ({len(raw_df)} rows)."}
        
        # Limit to the training window
        df_train = raw_df.tail(train_days).reset_index(drop=True)
        
        # Target labeling: Future 3-day return
        # Class 0: DOWN (< -2%), Class 1: HOLD (between -2% and 2%), Class 2: UP (> 2%)
        df_train['future_ret'] = df_train['Close'].shift(-3) / df_train['Close'] - 1.0
        
        def label_return(ret):
            if pd.isna(ret):
                return 1 # Fallback to HOLD
            if ret < -0.02:
                return 0
            if ret > 0.02:
                return 2
            return 1
            
        df_train['label'] = df_train['future_ret'].apply(label_return)
        
        # Preprocess features
        features_df = preprocess_features(df_train)
        if len(features_df) <= window_size + 3:
            return {"status": "error", "message": "Dataset too small after feature engineering."}
        
        # Split features and labels
        labels = features_df['label'].values
        scaled_data = scale_features(features_df)
        
        # Prepare sequences
        X = prepare_sequences(scaled_data, window_size=window_size)
        
        # Adjust lengths (since shift(-3) makes last 3 samples labels invalid for training)
        X_train = X[:-3]
        y_train = labels[window_size - 1:-3]
        
        # Train LSTM Model
        model = build_trend_model(window_size, X.shape[2])
        model.fit(X_train, y_train, epochs=10, batch_size=16, verbose=0)
        
        # Predict on latest sequence
        last_seq = X[-1:]
        probs = model.predict(last_seq, verbose=0)[0]
        pred_label = int(np.argmax(probs))
        
        labels_map = {0: "DOWN", 1: "HOLD", 2: "UP"}
        
        return {
            "status": "success",
            "prediction": labels_map[pred_label],
            "confidence": float(probs[pred_label]),
            "probabilities": {
                "DOWN": float(probs[0]),
                "HOLD": float(probs[1]),
                "UP": float(probs[2])
            }
        }
        
    except Exception as e:
        return {"status": "fallback", "message": str(e)}

# --- Core Tools Exposed to Agents ---

def get_anomaly_signals(
    symbol: Annotated[str, "Ticker symbol of the cryptocurrency (e.g., BTC-USD)"],
    curr_date: Annotated[str, "The current trading date, YYYY-MM-DD"],
    look_back_days: Annotated[int, "How many historical days to include in the analysis (default 60)"] = 60
) -> str:
    """Run TensorFlow Autoencoder Anomaly Detection and return a Markdown analysis summary."""
    res = run_anomaly_detection(symbol, curr_date, train_days=max(120, look_back_days * 2))
    
    header = f"### [TensorFlow Anomaly Detection Report for {symbol.upper()}]\n"
    header += f"Analysis Date: {curr_date}\n\n"
    
    if res["status"] == "success":
        anomaly_str = "**ANOMALY DETECTED** (High volatility or abnormal volume detected)" if res["is_anomaly"] else "NORMAL (Stable price action and volume)"
        
        md_table = "| Metric | Value |\n"
        md_table += "| --- | --- |\n"
        md_table += f"| **Market State** | {anomaly_str} |\n"
        md_table += f"| **Reconstruction MSE** | {res['anomaly_score']:.6f} |\n"
        md_table += f"| **Anomaly Threshold** | {res['threshold']:.6f} |\n"
        md_table += f"| **Total Historical Anomalies** | {res['total_anomalies_detected']} occurrences |\n"
        
        recent_dates = ", ".join(res["recent_anomalies"]) if res["recent_anomalies"] else "None"
        md_table += f"| **Recent Anomaly Dates** | {recent_dates} |\n"
        
        desc = ("\n**Analysis interpretation**:\n"
                "The Autoencoder model flags an anomaly when the reconstruction error of the recent price/volume window "
                "exceeds the 95th percentile threshold of historical volatility. "
                "If an anomaly is flagged, agents should exercise caution, watch out for volume surges or sudden liquidations, "
                "and consider tighter risk limits.")
        
        return header + md_table + desc
    
    else:
        # Fallback implementation: standard volatility based threshold
        try:
            df = load_ohlcv(symbol, curr_date)
            df = df.tail(look_back_days).reset_index(drop=True)
            if len(df) < 5:
                return f"{header}Error: Insufficient data for anomaly detection."
            
            df['returns'] = df['Close'].pct_change()
            vol = df['returns'].std()
            last_ret = df['returns'].iloc[-1]
            is_anomaly = abs(last_ret) > 2.0 * vol
            
            anomaly_str = "**ANOMALY DETECTED** (Price deviation > 2 standard deviations)" if is_anomaly else "NORMAL (Stable price returns)"
            
            md_table = "| Metric | Value |\n"
            md_table += "| --- | --- |\n"
            md_table += f"| **Market State (Fallback)** | {anomaly_str} |\n"
            md_table += f"| **Current Deviation** | {last_ret * 100:.2f}% |\n"
            md_table += f"| **Standard Volatility (σ)** | {vol * 100:.2f}% |\n"
            
            return header + md_table + f"\n*Fallback warning: TensorFlow model fell back to statistical deviation. Reason: {res.get('message', 'Unknown')}.*"
        except Exception as ex:
            return f"{header}Error executing anomaly detection: {str(ex)}"

def get_trend_predictions(
    symbol: Annotated[str, "Ticker symbol of the cryptocurrency (e.g., BTC-USD)"],
    curr_date: Annotated[str, "The current trading date, YYYY-MM-DD"],
    look_back_days: Annotated[int, "How many historical days to include in the analysis (default 60)"] = 60
) -> str:
    """Run TensorFlow LSTM Price Trend Forecasting and return a Markdown analysis summary."""
    res = run_trend_forecasting(symbol, curr_date, train_days=max(120, look_back_days * 2))
    
    header = f"### [TensorFlow Price Trend Forecast for {symbol.upper()}]\n"
    header += f"Analysis Date: {curr_date}\n\n"
    
    if res["status"] == "success":
        pred = res["prediction"]
        conf = res["confidence"] * 100
        probs = res["probabilities"]
        
        md_table = "| Parameter | Prediction Value |\n"
        md_table += "| --- | --- |\n"
        md_table += f"| **Forecasted Direction** | **{pred}** |\n"
        md_table += f"| **Confidence Level** | {conf:.1f}% |\n"
        md_table += f"| **Probability: UP** | {probs['UP']*100:.1f}% |\n"
        md_table += f"| **Probability: HOLD** | {probs['HOLD']*100:.1f}% |\n"
        md_table += f"| **Probability: DOWN** | {probs['DOWN']*100:.1f}% |\n"
        
        desc = ("\n**Model details**:\n"
                "The price forecasting sequence model (LSTM) evaluates the past sequential trends of returns, volatility, "
                "and volume momentum to classify the directional return over the next 3 days. "
                "A forecast of UP/DOWN indicates positive/negative momentum; HOLD represents a sideways consolidation.")
        
        return header + md_table + desc
        
    else:
        # Fallback implementation: Moving average cross-over momentum
        try:
            df = load_ohlcv(symbol, curr_date)
            df = df.tail(look_back_days).reset_index(drop=True)
            if len(df) < 20:
                return f"{header}Error: Insufficient data for trend predictions."
                
            sma_10 = df['Close'].rolling(window=10).mean().iloc[-1]
            sma_20 = df['Close'].rolling(window=20).mean().iloc[-1]
            curr_price = df['Close'].iloc[-1]
            
            if curr_price > sma_10 and sma_10 > sma_20:
                pred = "UP"
                conf = 65.0
            elif curr_price < sma_10 and sma_10 < sma_20:
                pred = "DOWN"
                conf = 65.0
            else:
                pred = "HOLD"
                conf = 55.0
                
            md_table = "| Parameter | Prediction Value |\n"
            md_table += "| --- | --- |\n"
            md_table += f"| **Forecasted Direction (Fallback)** | **{pred}** |\n"
            md_table += f"| **Assumed Confidence** | {conf:.1f}% |\n"
            md_table += f"| **Current Price** | {curr_price:.2f} |\n"
            md_table += f"| **SMA-10** | {sma_10:.2f} |\n"
            md_table += f"| **SMA-20** | {sma_20:.2f} |\n"
            
            return header + md_table + f"\n*Fallback warning: TensorFlow model fell back to moving average crossover. Reason: {res.get('message', 'Unknown')}.*"
        except Exception as ex:
            return f"{header}Error executing trend forecasting: {str(ex)}"
