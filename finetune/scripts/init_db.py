import sqlite3
import os

DB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "db"))
DB_PATH = os.path.join(DB_DIR, "finetune_data.db")

def init_db():
    print(f"Creating directory: {DB_DIR}")
    os.makedirs(DB_DIR, exist_ok=True)
    
    print(f"Connecting to database at: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. raw_examples table
    print("Creating raw_examples table...")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS raw_examples (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker          TEXT NOT NULL,               -- VD: "BTC-USD", "NVDA"
        trade_date      TEXT NOT NULL,               -- VD: "2026-06-15" (YYYY-MM-DD)
        asset_type      TEXT NOT NULL DEFAULT 'stock', -- "crypto" hoặc "stock"
        
        -- Dữ liệu từ 3 nguồn
        news_block      TEXT,                        -- Raw text từ Yahoo Finance News
        stocktwits_block TEXT,                       -- Raw text từ StockTwits API
        reddit_block    TEXT,                        -- Raw text từ Reddit API
        
        -- System message đã build (giống hệt agent thật)
        system_message  TEXT NOT NULL,               -- Full system prompt
        
        -- Metadata
        news_article_count    INTEGER DEFAULT 0,     -- Số bài báo trong news_block
        stocktwits_msg_count  INTEGER DEFAULT 0,     -- Số messages StockTwits
        stocktwits_bullish    INTEGER DEFAULT 0,     -- Số messages Bullish
        stocktwits_bearish    INTEGER DEFAULT 0,     -- Số messages Bearish
        reddit_post_count     INTEGER DEFAULT 0,     -- Số posts Reddit
        
        -- Tracking
        collected_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        UNIQUE(ticker, trade_date)                   -- Mỗi ticker+date chỉ 1 record
    );
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_ticker ON raw_examples(ticker);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_date ON raw_examples(trade_date);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_asset_type ON raw_examples(asset_type);")

    # 2. golden_responses table
    print("Creating golden_responses table...")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS golden_responses (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_example_id  INTEGER NOT NULL,            -- FK -> raw_examples.id
        ticker          TEXT NOT NULL,
        trade_date      TEXT NOT NULL,
        
        -- Golden response
        golden_response TEXT NOT NULL,                -- Full response từ gpt-oss-120b
        
        -- Phân tích tự động từ golden response
        sentiment_direction TEXT,                    -- "Bullish" / "Bearish" / "Neutral" / "Mixed"
        has_source_breakdown BOOLEAN DEFAULT 0,      -- Có section breakdown không
        has_divergence_analysis BOOLEAN DEFAULT 0,   -- Có phân tích divergence không
        has_catalysts_risks BOOLEAN DEFAULT 0,       -- Có catalysts/risks không
        has_markdown_table BOOLEAN DEFAULT 0,        -- Có markdown table không
        structure_score REAL DEFAULT 0,              -- 0.0 -> 1.0 (đủ mấy sections)
        
        -- API metadata
        model_used      TEXT DEFAULT 'gpt-oss-120b', -- Model đã sinh response
        api_endpoint    TEXT DEFAULT 'mkp-api.fptcloud.com',
        tokens_input    INTEGER DEFAULT 0,           -- Input tokens
        tokens_output   INTEGER DEFAULT 0,           -- Output tokens
        latency_ms      INTEGER DEFAULT 0,           -- Thời gian response (ms)
        
        -- Tracking
        generated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        FOREIGN KEY (raw_example_id) REFERENCES raw_examples(id)
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_golden_ticker ON golden_responses(ticker);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_golden_direction ON golden_responses(sentiment_direction);")

    # 3. dataset_splits table
    print("Creating dataset_splits table...")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS dataset_splits (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        golden_id       INTEGER NOT NULL,            -- FK -> golden_responses.id
        ticker          TEXT NOT NULL,
        trade_date      TEXT NOT NULL,
        split           TEXT NOT NULL,               -- "train" / "val" / "test"
        
        -- ChatML formatted message (full prompt + response)
        system_content  TEXT NOT NULL,               -- System message
        user_content    TEXT NOT NULL DEFAULT 'Continue',
        assistant_content TEXT NOT NULL,             -- Golden response
        
        -- Token counts
        total_tokens    INTEGER DEFAULT 0,           -- Tổng tokens (approx)
        
        FOREIGN KEY (golden_id) REFERENCES golden_responses(id)
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_split ON dataset_splits(split);")

    # 4. eval_results table
    print("Creating eval_results table...")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS eval_results (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        model_name      TEXT NOT NULL,               -- "qwen3:4b" hoặc "sentiment-analyst-ft"
        test_example_id INTEGER NOT NULL,            -- FK -> dataset_splits.id (split="test")
        ticker          TEXT NOT NULL,
        trade_date      TEXT NOT NULL,
        
        -- Model response
        model_response  TEXT NOT NULL,               -- Response từ model đang eval
        
        -- Metric scores
        structure_score REAL,                        -- 0.0 -> 1.0
        rouge1_f        REAL,                        -- ROUGE-1 F1
        rouge2_f        REAL,                        -- ROUGE-2 F1
        rougeL_f        REAL,                        -- ROUGE-L F1
        sentiment_direction_pred TEXT,               -- Predicted direction
        sentiment_direction_ref  TEXT,               -- Reference direction
        sentiment_match BOOLEAN,                     -- pred == ref?
        
        -- GPT-as-Judge scores (nullable - chỉ chạy trên sample)
        judge_accuracy      REAL,                    -- 1-5 scale
        judge_evidence      REAL,
        judge_structure     REAL,
        judge_actionability REAL,
        judge_nuance        REAL,
        judge_average       REAL,
        
        -- Tracking
        evaluated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_eval_model ON eval_results(model_name);")

    conn.commit()
    conn.close()
    print("Database and indices initialized successfully!")

if __name__ == "__main__":
    init_db()
