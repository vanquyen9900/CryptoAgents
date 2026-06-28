"""Regime-aware vector memory for CryptoAgents — Trụ cột C2.

Theo research_report.md §3.4:
  Bộ truy xuất hai bước trên kho C1:
    (i)  Lọc metadata theo regime (lấy nhãn từ Trụ cột B HMM)
    (ii) Xếp hạng cosine trên vector embedding của reflection, lấy top-3
  Lưu trữ trong ChromaDB (ANN ~ O(log N)); chi phí thêm không đáng kể so
  với một LLM call. Đây là bản tổng quát hoá ý tưởng "nhớ + theo pha",
  thay khối FIFO-5 cũ.

Graceful degradation:
  Nếu ``chromadb`` hoặc ``sentence-transformers`` chưa được cài, module
  tự động fallback về FIFO và log một WARNING duy nhất (không crash).
  Người dùng bật tính năng này bằng cách cài thêm các package và set
  ``vector_memory_enabled: true`` trong config.

Install (optional):
  pip install chromadb sentence-transformers
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# ─── Optional dependency guard ────────────────────────────────────────────────
try:
    import chromadb
    from chromadb.config import Settings
    _CHROMA_AVAILABLE = True
except ImportError:  # pragma: no cover
    _CHROMA_AVAILABLE = False
    logger.warning(
        "chromadb not installed — RegimeAwareVectorMemory will use FIFO fallback. "
        "Install with: pip install chromadb sentence-transformers"
    )

try:
    from sentence_transformers import SentenceTransformer
    _ST_AVAILABLE = True
except ImportError:  # pragma: no cover
    _ST_AVAILABLE = False
    if _CHROMA_AVAILABLE:
        logger.warning(
            "sentence-transformers not installed — embedding will use character n-gram fallback. "
            "Install with: pip install sentence-transformers"
        )

# ─── Lightweight fallback embedder (no extra dependency) ──────────────────────

def _ngram_embed(text: str, dim: int = 128) -> List[float]:
    """Deterministic character n-gram pseudo-embedding (fallback only).

    Not semantically meaningful — used solely when sentence-transformers
    is absent.  Dimension is kept small to avoid ChromaDB overhead.
    """
    import hashlib
    vec = [0.0] * dim
    text_norm = text.lower()
    for i in range(len(text_norm) - 2):
        tri = text_norm[i : i + 3]
        h = int(hashlib.md5(tri.encode()).hexdigest(), 16) % dim
        vec[h] += 1.0
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


# ─── Main class ───────────────────────────────────────────────────────────────

class RegimeAwareVectorMemory:
    """Persistent regime-aware vector memory backed by ChromaDB.

    Two-step retrieval (report §3.4):
      Step 1 — Metadata filter: keep only entries whose ``regime`` tag matches
               the current HMM-detected regime (Bull / Bear / Sideway).
      Step 2 — Cosine similarity: rank filtered candidates by embedding of
               their ``reflection`` text; return top-k.

    The ``regime`` label must come from the TensorFlow HMM Regime Analyst
    (Trụ cột B) that already runs in Phase 1 of the pipeline.

    Falls back to FIFO if ChromaDB is not available (see module docstring).
    """

    # Supported regime labels (must match output of quantitative_models.py)
    REGIME_LABELS = frozenset({"Bull", "Bear", "Sideway"})

    def __init__(
        self,
        persist_directory: str,
        collection_name: str = "trading_memory",
        embedding_model: str = "all-MiniLM-L6-v2",
        top_k: int = 3,
    ):
        """Initialise the vector store.

        Args:
            persist_directory: Path where ChromaDB stores its data.
            collection_name:   ChromaDB collection name.
            embedding_model:   SentenceTransformer model identifier.
            top_k:             Number of memories to return per query.
        """
        self.top_k = top_k
        self._available = _CHROMA_AVAILABLE

        if not self._available:
            return

        # ── Embedding function ────────────────────────────────
        if _ST_AVAILABLE:
            self._model = SentenceTransformer(embedding_model)
            self._embed = lambda text: self._model.encode(text).tolist()
            logger.info("VectorMemory: using SentenceTransformer '%s'", embedding_model)
        else:
            self._embed = _ngram_embed
            logger.warning("VectorMemory: using character n-gram fallback embedder")

        # ── ChromaDB client ────────────────────────────────────
        self._client = chromadb.PersistentClient(
            path=persist_directory,
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},  # cosine distance for all queries
        )
        logger.info(
            "VectorMemory: ChromaDB collection '%s' at '%s' (%d entries)",
            collection_name, persist_directory, self._collection.count(),
        )

    # ── Write ─────────────────────────────────────────────────────────────────

    def add_entry(
        self,
        *,
        entry_id: str,
        ticker: str,
        regime: str,
        reflection: str,
        trade_date: str,
        rating: str = "",
        raw_return: Optional[float] = None,
        alpha_return: Optional[float] = None,
    ) -> None:
        """Upsert a resolved memory entry into ChromaDB.

        Args:
            entry_id:    Unique ID (use trade_date + ticker + hash).
            ticker:      Asset symbol, e.g. "AAPL" or "BTC-USD".
            regime:      HMM regime label: "Bull", "Bear", or "Sideway".
            reflection:  LLM-generated reflection text (the text to embed).
            trade_date:  Date string YYYY-MM-DD.
            rating:      Decision rating e.g. "Buy", "Hold", "Sell".
            raw_return:  Realised raw return (for metadata; not used in retrieval).
            alpha_return: Alpha vs benchmark (for metadata; not used in retrieval).
        """
        if not self._available:
            return

        regime_tag = regime if regime in self.REGIME_LABELS else "Sideway"
        embedding = self._embed(reflection)
        metadata = {
            "ticker": ticker,
            "regime": regime_tag,
            "trade_date": trade_date,
            "rating": rating,
            "raw_return": raw_return if raw_return is not None else 0.0,
            "alpha_return": alpha_return if alpha_return is not None else 0.0,
        }
        self._collection.upsert(
            ids=[entry_id],
            embeddings=[embedding],
            documents=[reflection],
            metadatas=[metadata],
        )
        logger.debug("VectorMemory: upserted entry %s (regime=%s)", entry_id, regime_tag)

    # ── Read ──────────────────────────────────────────────────────────────────

    def retrieve(
        self,
        *,
        ticker: str,
        regime: str,
        query_text: str,
        top_k: Optional[int] = None,
    ) -> List[dict]:
        """Two-step retrieval: regime filter → cosine similarity.

        Args:
            ticker:     Asset symbol for which to retrieve memories.
            regime:     Current HMM regime label (from Regime Analyst output).
            query_text: Text to embed for similarity search (e.g. current decision).
            top_k:      Override instance default.

        Returns:
            List of dicts with keys: ticker, regime, trade_date, rating,
            raw_return, alpha_return, reflection (= document text).
            Empty list if ChromaDB unavailable or no matching entries.
        """
        if not self._available or self._collection.count() == 0:
            return []

        k = top_k or self.top_k
        regime_tag = regime if regime in self.REGIME_LABELS else "Sideway"
        query_embedding = self._embed(query_text)

        # ── Step 1: metadata pre-filter (regime) ──────────────
        # ChromaDB ``where`` clause; also accept ANY-regime entries (e.g. cross-ticker lessons)
        try:
            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=min(k * 4, max(1, self._collection.count())),  # over-fetch then re-rank
                where={"regime": {"$in": [regime_tag, "ANY"]}},
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("VectorMemory: ChromaDB query failed: %s — returning empty", exc)
            return []

        # ── Step 2: build result list (already cosine-ranked by ChromaDB) ─
        memories: List[dict] = []
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]

        for doc, meta in zip(docs, metas):
            memories.append(
                {
                    "ticker": meta.get("ticker", ""),
                    "regime": meta.get("regime", ""),
                    "trade_date": meta.get("trade_date", ""),
                    "rating": meta.get("rating", ""),
                    "raw_return": meta.get("raw_return", 0.0),
                    "alpha_return": meta.get("alpha_return", 0.0),
                    "reflection": doc,
                }
            )
            if len(memories) >= k:
                break

        logger.debug(
            "VectorMemory: retrieved %d/%d entries (regime=%s, ticker=%s)",
            len(memories), k, regime_tag, ticker,
        )
        return memories

    # ── Formatting ────────────────────────────────────────────────────────────

    @staticmethod
    def format_for_prompt(memories: List[dict]) -> str:
        """Format retrieved memories as a markdown string for LLM injection.

        Matches the style of TradingMemoryLog._format_full() so the PM
        receives a coherent context block regardless of which backend supplied
        the memories.
        """
        if not memories:
            return ""
        parts = ["## Past Experiences (Regime-matched, vector retrieved)"]
        for i, m in enumerate(memories, 1):
            raw = f"{m['raw_return']:+.1%}" if m.get("raw_return") else "n/a"
            alpha = f"{m['alpha_return']:+.1%}" if m.get("alpha_return") else "n/a"
            parts.append(
                f"\n### Memory {i} | {m['trade_date']} | {m['ticker']} | "
                f"{m['rating']} | Return: {raw} | Alpha: {alpha} | Regime: {m['regime']}"
            )
            parts.append(m["reflection"])
        return "\n".join(parts)

    @property
    def available(self) -> bool:
        """True if ChromaDB is importable and initialised."""
        return self._available

    def count(self) -> int:
        """Total number of entries in the collection."""
        if not self._available:
            return 0
        return self._collection.count()
