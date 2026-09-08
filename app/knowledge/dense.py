"""Dense retrieval using shared assembly (Phase 2 path)."""

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
from app.knowledge.store import RetrievedChunk, index_ready, query_chunks


@dataclass(frozen=True)
class DenseSelection:
    pack_ids: list[str]
    content: str
    scores: dict[str, float] = field(default_factory=dict)
    chunk_ids: list[str] = field(default_factory=list)
    truncated: bool = False
    no_answer: bool = False
    hits: list[RetrievedChunk] = field(default_factory=list)


def _from_assembled(asm: AssembledKnowledge) -> DenseSelection:
    return DenseSelection(
        pack_ids=list(asm.pack_ids),
        content=asm.content,
        scores=dict(asm.scores),
        chunk_ids=list(asm.chunk_ids),
        truncated=asm.truncated,
        no_answer=asm.no_answer,
        hits=list(asm.hits),
    )


def select_dense(
    query: str,
    *,
    settings: Settings | None = None,
    embeddings: EmbeddingsClient | None = None,
) -> DenseSelection | None:
    """Retrieve top-K chunks. Returns None if the index is unavailable."""
    cfg = settings or get_settings()
    if not cfg.que_rag_enabled or not index_ready(cfg):
        return None

    q = (query or "").strip()
    if not q:
        # Empty query → CORE only, not a failed retrieval.
        core_id, core_body = load_core_text()
        core_body, _ = truncate_text(core_body, 8_500)
        parts = [preamble(no_answer=False)]
        pack_ids: list[str] = []
        if core_body:
            parts.append(f"### QUE Core Product Knowledge\n{core_body}")
            pack_ids.append(core_id)
        return DenseSelection(pack_ids=pack_ids, content="\n\n".join(parts).strip())

    emb = embeddings or get_embeddings(settings=cfg)
    vector = emb.embed_query(q)
    hits = query_chunks(vector, top_k=cfg.que_rag_top_k, settings=cfg)
    kept = [h for h in hits if h.score >= cfg.que_rag_min_score]
    no_answer = not kept
    asm = assemble_selection(kept if kept else hits, no_answer=no_answer, score_label="score")
    return _from_assembled(asm)
