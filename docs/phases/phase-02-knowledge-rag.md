# Phase 2 — Knowledge System + Dense RAG

**Status:** Done  
**Goal:** Ground QUE in Quizzer product truth (click paths, SAY/NEVER) via committed markdown + dense retrieval — without inventing UI or live numbers.

---

## Problem this phase solved

Phase 1 QUE could stay on-topic but still hallucinate:

- Wrong button names / nav paths
- Outdated workflows
- Confident answers when docs don’t cover the ask

**Upgrade story:** treat product knowledge as **versioned data** under `knowledge/`, select the right chunks per turn (dense RAG + keyword fallback), and inject them as system context — never as invented facts.

---

## What we built

### Knowledge as data (committed)

- Domain folders under `knowledge/` (exams, account, arena, …)
- `knowledge/CORE.md` — always injected product map + answer contract
- `knowledge/manifest.json` — pack index / keywords / limits
- Writing rules: answer-oriented guides with click paths and SAY/NEVER (`knowledge/README.md`)

**Critical deploy rule:** `knowledge/` is copied into the Docker image. Without it, production QUE has no product brain.

### Ingestion pipeline

```text
markdown files
  → chunk (section-aware)
  → embed (OpenAI-compatible text-embedding-3-small via API)
  → Chroma persist at QUE_CHROMA_PATH (default data/chroma/)
```

CLI:

```bash
uv run python -m app.knowledge --force
```

### Runtime retrieval

1. Prefer **dense** query against Chroma (`app/knowledge/dense.py` + `store.py`)
2. Take top-**K** (`QUE_RAG_TOP_K`, default **6**)
3. Drop hits below `QUE_RAG_MIN_SCORE` (default **0.28**) → honest no-answer / CORE-only
4. If index missing/corrupt → **keyword fallback** from manifest (`retrieve.py`)

**Rerank / hybrid BM25:** not implemented (handbook Phase 6).

### Graph wiring

Knowledge node injects selected packs into the prompt after identity:

```text
prepare → … → knowledge → generate
```

(Phase 3 inserts `context` before knowledge; Phase 4 may skip knowledge for tools.)

---

## How retrieval works on a turn

```text
user question (+ resolved_query)
  → select_knowledge()
       dense hits? → top-K above min score
       else keyword packs (max_guides)
  → SystemMessage with guide text (frontmatter stripped)
  → LLM answers using packs privately (don’t dump raw docs)
```

---

## Key files

| File | Role |
|---|---|
| `knowledge/**` | Product brain (markdown) |
| `knowledge/CORE.md` | Always-on core |
| `knowledge/manifest.json` | Pack registry |
| `app/knowledge/chunking.py` | Split guides into embeddable chunks |
| `app/knowledge/embeddings.py` | Embedding client |
| `app/knowledge/store.py` | Chroma collection open/query/upsert |
| `app/knowledge/build_index.py` | Build/rebuild index |
| `app/knowledge/dense.py` | Dense selection path |
| `app/knowledge/retrieve.py` | Keyword fallback + orchestration |
| `app/knowledge/__main__.py` | `python -m app.knowledge` CLI |
| `app/graphs/nodes.py` → `knowledge_node` | Inject packs into graph state |
| `evals/retrieval_cases.json` | Retrieval golden set |
| `scripts/run_retrieval_eval.py` | recall@K / precision@K |
| `tests/test_rag.py`, `tests/test_chunking.py`, `tests/test_knowledge.py` | Unit tests |

### Config knobs

| Env | Meaning | Default |
|---|---|---|
| `QUE_RAG_ENABLED` | Master switch | true |
| `QUE_CHROMA_PATH` | Persist dir | `data/chroma` |
| `QUE_EMBEDDING_MODEL` | Embedding model id | `openai/text-embedding-3-small` |
| `QUE_RAG_TOP_K` | Dense K | **6** |
| `QUE_RAG_MIN_SCORE` | Cosine floor | 0.28 |
| `QUE_RAG_FALLBACK_KEYWORD` | Fallback if no index | true |

---

## Measured outcome

Dense retrieval eval (after index build): **recall@5 ≈ 0.91** on the golden set (see `BUILD_PROGRESS.md`).

---

## Important improvements

1. **Knowledge ≠ identity** — persona stays thin; docs stay in `knowledge/`.
2. **API embeddings** — no giant local model download in deploy.
3. **Min-score honesty** — don’t force a bad chunk into the answer.
4. **Keyword fallback** — service still helpful if Chroma isn’t built yet.
5. **Eval before “more RAG features”** — hybrid/rerank wait for evidence (Phase 6).

---

## Interview talking points

- “Dense vs keyword?” → dense for meaning; keyword as resilience + early path.
- “What’s your K?” → `QUE_RAG_TOP_K=6`; filter by min score.
- “Do you rerank?” → Not yet; Phase 6 if miss clusters show lexical/hybrid need.
- “How do you prevent hallucinated product UI?” → SAY/NEVER in guides + CORE answer contract + retrieval grounding.

---

## What we deliberately did *not* do yet

- Hybrid search / cross-encoder rerank → **hybrid BM25+RRF shipped in Phase 6**; CE still deferred
- Multi-corpus permissions on docs
- Live account numbers from RAG (impossible — needs tools)

---

## How to verify

```bash
uv run python -m app.knowledge --force
uv run python scripts/run_retrieval_eval.py --mode dense
uv run pytest tests/test_rag.py tests/test_chunking.py -q
```
