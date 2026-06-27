import os
import pandas as pd
import json
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

def save_parquet(df: pd.DataFrame, dataset_name: str, layer: str = "normalized", partition_cols=None, mode="overwrite"):
    """
    Lưu df ra data/{layer}/{dataset_name} dưới dạng parquet.
    """
    out_dir = DATA_DIR / layer / dataset_name

    if mode == "overwrite" and out_dir.exists():
        shutil.rmtree(out_dir)

    out_dir.mkdir(parents=True, exist_ok=True)

    if partition_cols:
        df.to_parquet(out_dir, partition_cols=partition_cols, engine="pyarrow", index=False)
    else:
        out_file = out_dir / "data.parquet"
        df.to_parquet(out_file, engine="pyarrow", index=False)

    return str(out_dir)

def save_raw_json(data: dict, dataset_name: str, file_name: str):
    """
    Lưu raw data ra data/raw/{dataset_name}/{file_name}
    """
    out_dir = DATA_DIR / "raw" / dataset_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / file_name
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    return str(out_file)

def load_dataset(dataset_name: str, layer: str = "normalized") -> pd.DataFrame:
    """
    Load dataset từ file Parquet (hỗ trợ đọc cả thư mục nếu chia partition).
    """
    in_dir = DATA_DIR / layer / dataset_name
    if not in_dir.exists():
        raise FileNotFoundError(f"Dataset {dataset_name} in layer {layer} does not exist.")
    return pd.read_parquet(in_dir, engine="pyarrow")
