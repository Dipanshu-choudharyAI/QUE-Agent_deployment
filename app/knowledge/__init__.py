"""Product knowledge package — markdown packs under /knowledge, selected at runtime.

Phase 2 adds dense RAG (chunk → embed → Chroma) while keeping keyword fallback.
"""

from app.knowledge.retrieve import (
    KnowledgeSelection,
    clear_knowledge_caches,
    knowledge_available,
    select_knowledge,
    validate_knowledge_manifest,
)

__all__ = [
    "KnowledgeSelection",
    "clear_knowledge_caches",
    "knowledge_available",
    "select_knowledge",
    "validate_knowledge_manifest",
]
