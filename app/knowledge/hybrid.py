"""Hybrid retrieval: dense Chroma + BM25 fused with reciprocal rank fusion (RRF).

Phase 6 — evidence: dense miss clusters were complementary to lexical hits
(e.g. terminology / exam-settings). Neural cross-encoder rerank is deferred.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import Settings, get_settings
from app.knowledge.assemble import (
    AssembledKnowledge,
    assemble_selection,
    load_core_text,
    preamble,
    truncate_text,
)
from app.knowledge.embeddings import EmbeddingsClient, get_embeddings
from app.knowledge.sparse import query_bm25, sparse_ready
from app.knowledge.store import RetrievedChunk, index_ready, query_chunks


@dataclass(frozen=True)
class HybridSelection:
    pack_ids: list[str]
    content: str
    scores: dict[str, float] = field(default_factory=dict)
    chunk_ids: list[str] = field(default_factory=list)
    truncated: bool = False
    no_answer: bool = False
    hits: list[RetrievedChunk] = field(default_factory=list)
    mode: str = "hybrid"


def reciprocal_rank_fusion(
    ranked_lists: list[list[RetrievedChunk]],
    *,
    rrf_k: int = 60,
) -> list[RetrievedChunk]:
    """Classic RRF: score = Σ 1/(rrf_k + rank). Rank is 1-based within each list."""
    fused: dict[str, float] = {}
    by_id: dict[str, RetrievedChunk] = {}
    for hits in ranked_lists:
        for rank, hit in enumerate(hits, start=1):
            cid = hit.chunk_id
            if not cid:
                continue
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (rrf_k + rank)
            # Prefer the first-seen chunk body; keep max provenance score for labels.
            prior = by_id.get(cid)
            if prior is None or hit.score > prior.score:
                by_id[cid] = hit
    ordered = sorted(fused.items(), key=lambda item: (-item[1], item[0]))
    out: list[RetrievedChunk] = []
    for cid, rrf_score in ordered:
        base = by_id[cid]
        out.append(
            RetrievedChunk(
                chunk_id=base.chunk_id,
                doc_id=base.doc_id,
                path=base.path,
                title=base.title,
                section=base.section,
                text=base.text,
                score=float(rrf_score),
                corpus_version=base.corpus_version,
            )
        )
    return out


def _from_assembled(asm: AssembledKnowledge, *, mode: str = "hybrid") -> HybridSelection:
    return HybridSelection(
        pack_ids=list(asm.pack_ids),
        content=asm.content,
        scores=dict(asm.scores),
        chunk_ids=list(asm.chunk_ids),
        truncated=asm.truncated,
        no_answer=asm.no_answer,
        hits=list(asm.hits),
        mode=mode,
    )


def select_hybrid(
    query: str,
    *,
    settings: Settings | None = None,
    embeddings: EmbeddingsClient | None = None,
) -> HybridSelection | None:
    """Dense + BM25 → RRF → top-K. Returns None if dense index unavailable."""
    cfg = settings or get_settings()
    if not cfg.que_rag_enabled or not index_ready(cfg):
        return None

    q = (query or "").strip()
    if not q:
        core_id, core_body = load_core_text()
        core_body, _ = truncate_text(core_body, 8_500)
        parts = [preamble(no_answer=False)]
        pack_ids: list[str] = []
        if core_body:
            parts.append(f"### QUE Core Product Knowledge\n{core_body}")
            pack_ids.append(core_id)
        return HybridSelection(pack_ids=pack_ids, content="\n\n".join(parts).strip(), mode="hybrid")

    candidate_k = max(int(cfg.que_rag_candidate_k), int(cfg.que_rag_top_k))
    emb = embeddings or get_embeddings(settings=cfg)
    vector = emb.embed_query(q)
    dense_hits = query_chunks(vector, top_k=candidate_k, settings=cfg)

    sparse_hits: list[RetrievedChunk] = []
    if sparse_ready(cfg):
        sparse_hits = query_bm25(q, top_k=candidate_k, settings=cfg)

    if sparse_hits:
        fused = reciprocal_rank_fusion(
            [dense_hits, sparse_hits],
            rrf_k=int(cfg.que_rag_rrf_k),
        )
        mode = "hybrid"
    else:
        fused = dense_hits
        mode = "dense"

    top = fused[: int(cfg.que_rag_top_k)]

    # Honest no-answer stays dense-gated: BM25 alone must not invent product
    # packs for out-of-domain asks (e.g. weather). Sparse still enriches recall
    # when at least one fused top hit also clears the dense cosine floor.
    dense_by_id = {h.chunk_id: h for h in dense_hits}
    dense_ok = any(
        (dense_by_id[h.chunk_id].score >= cfg.que_rag_min_score)
        for h in top
        if h.chunk_id in dense_by_id
    )
    # If fusion demoted all dense hits below top-K, still accept when any dense
    # candidate clears the floor (sparse-only top would otherwise starve).
    if not dense_ok:
        dense_ok = any(h.score >= cfg.que_rag_min_score for h in dense_hits)

    no_answer = not dense_ok
    if no_answer:
        asm = assemble_selection(top, no_answer=True, score_label="rrf")
        return _from_assembled(asm, mode=mode)

    asm = assemble_selection(top, no_answer=False, score_label="rrf" if sparse_hits else "score")
    return _from_assembled(asm, mode=mode)
