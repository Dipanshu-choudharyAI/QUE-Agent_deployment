# Phase 6 — Hybrid retrieval (BM25 + RRF)

**Status:** Done  
**Goal:** Fuse dense embedding search with chunk-level BM25 so exact-term / complementary misses improve — only after Phase 2 eval evidence justified it.

---

## Evidence gate (why now)

Dense-only Phase 2 baseline on `evals/retrieval_cases.json`:

| Mode | recall@5 | precision@5 |
|---|---|---|
| Dense (Phase 2) | **0.9118** | 0.398 |
| Keyword (manifest) | 0.9412 | 0.647 |

Complementary pattern: dense missed packs that lexical matching found (and vice versa). Classic signal for hybrid — not speculation.

---

## What we built

```text
Query
  ├── Dense Chroma (candidate_k=20)
  └── BM25 over bm25_corpus.json (same chunks)
         │
         ▼
    Reciprocal Rank Fusion (rrf_k=60)
         │
         ▼
    Top QUE_RAG_TOP_K + dense min-score honesty → CORE + chunks
```

| Piece | Location |
|---|---|
| Sparse corpus write | [`app/knowledge/ingest.py`](../../app/knowledge/ingest.py) → `{QUE_CHROMA_PATH}/bm25_corpus.json` |
| BM25 query | [`app/knowledge/sparse.py`](../../app/knowledge/sparse.py) (Lucene-style IDF on `rank_bm25`) |
| RRF + select | [`app/knowledge/hybrid.py`](../../app/knowledge/hybrid.py) |
| Shared assemble | [`app/knowledge/assemble.py`](../../app/knowledge/assemble.py) |
| Wiring | [`app/knowledge/retrieve.py`](../../app/knowledge/retrieve.py) — hybrid when `QUE_RAG_HYBRID` + corpus ready |
| Config | `QUE_RAG_HYBRID`, `QUE_RAG_CANDIDATE_K`, `QUE_RAG_RRF_K` |

**No-answer honesty:** still dense-gated (`QUE_RAG_MIN_SCORE`). BM25 alone cannot force product packs for out-of-domain asks (weather).

---

## Measured outcome

After rebuild (`uv run python -m app.knowledge`):

| Mode | recall@5 | precision@5 | no_answer | latency p95 |
|---|---|---|---|---|
| Dense | 0.9118 | 0.398 | 1/1 | — |
| **Hybrid** | **0.9265** | **0.4275** | 1/1 | **1878 ms** (includes embed API) |

Delta: **+0.015 recall@5** vs dense baseline (notably recovers cases like r26). Remaining misses (r14 terminology, r25 workflows, r31 exam-settings) are content/BM25 ranking gaps — not fixed by a cross-encoder yet.

---

## What we deliberately deferred

- **Neural / cross-encoder rerank** — extra dep + P95 risk; handbook task `p6-t3` left open until miss clusters clearly need it
- Query rewriting
- Manifest-keyword as a third fusion list

---

## Interview talking points

- “Why hybrid after dense?” → measured complementary misses; keyword alone beat dense precision on the golden set.
- “Why RRF not score blending?” → rank fusion avoids mixing cosine and BM25 scales.
- “Why no cross-encoder?” → recall already improved; CE waits for a latency budget and a miss pattern it uniquely fixes.
- “How do you keep OOD honest?” → dense min-score still gates no-answer; sparse only enriches when dense already has confidence.

---

## How to verify

```bash
uv run python -m app.knowledge          # writes Chroma + bm25_corpus.json
uv run python scripts/run_retrieval_eval.py --mode dense
uv run python scripts/run_retrieval_eval.py --mode hybrid --latency
uv run pytest tests/test_hybrid.py tests/test_rag.py -q
```
