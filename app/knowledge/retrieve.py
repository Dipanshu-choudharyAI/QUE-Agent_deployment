"""Load and select QUE product knowledge packs for the LangGraph knowledge node.

No embeddings — keyword match against the latest user message + always-on CORE.
Manifest-driven: knowledge/manifest.json lists every injectable document.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

KNOWLEDGE_ROOT = Path(__file__).resolve().parents[2] / "knowledge"
MANIFEST_PATH = KNOWLEDGE_ROOT / "manifest.json"

# Prompt budget — CORE + up to max_guides (manifest default 3). Docs are long;
# we strip frontmatter and cap per-doc so free-tier models still fit.
_MAX_CHARS_TOTAL = 22_000
_MAX_CORE_CHARS = 8_500
_MAX_GUIDE_CHARS = 5_500
_MAX_GUIDES_DEFAULT = 3

_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
_FALLBACK_GUIDE_IDS = ("lifecycle", "common-workflows", "product-overview")


@dataclass(frozen=True)
class KnowledgeSelection:
    """Selected pack ids and the text block to inject as a system message."""

    pack_ids: list[str]
    content: str
    scores: dict[str, int] = field(default_factory=dict)
    truncated: bool = False


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _strip_frontmatter(text: str) -> str:
    """Drop YAML --- ... --- header so the model sees product prose only."""
    return _FRONTMATTER_RE.sub("", text, count=1).strip()


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    cut = text[: limit - 20].rsplit("\n", 1)[0]
    if len(cut) < limit // 2:
        cut = text[: limit - 20]
    return cut.rstrip() + "\n…[truncated]", True


def knowledge_available() -> bool:
    """True when knowledge/manifest.json is present (often gitignored locally)."""
    return MANIFEST_PATH.is_file()


@lru_cache
def _load_manifest() -> dict:
    if not MANIFEST_PATH.is_file():
        return {"documents": [], "max_guides": _MAX_GUIDES_DEFAULT}
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@lru_cache
def _read_pack(relative_path: str) -> str:
    path = KNOWLEDGE_ROOT / relative_path
    raw = path.read_text(encoding="utf-8")
    return _strip_frontmatter(raw)


def clear_knowledge_caches() -> None:
    """Test helper — drop manifest/file caches after fixture edits."""
    _load_manifest.cache_clear()
    _read_pack.cache_clear()


def validate_knowledge_manifest() -> list[str]:
    """Return list of problems (empty = healthy). Used by tests/startup checks."""
    problems: list[str] = []
    if not MANIFEST_PATH.is_file():
        return ["manifest missing (knowledge/ not checked out)"]
    try:
        manifest = _load_manifest()
    except (OSError, json.JSONDecodeError) as exc:
        return [f"manifest unreadable: {exc}"]

    docs = list(manifest.get("documents") or [])
    if not docs:
        problems.append("manifest has no documents")
    seen: set[str] = set()
    for doc in docs:
        doc_id = str(doc.get("id") or "")
        rel = str(doc.get("path") or "")
        if not doc_id:
            problems.append(f"document missing id: {doc!r}")
            continue
        if doc_id in seen:
            problems.append(f"duplicate id: {doc_id}")
        seen.add(doc_id)
        if not rel:
            problems.append(f"{doc_id}: missing path")
            continue
        path = KNOWLEDGE_ROOT / rel
        if not path.is_file():
            problems.append(f"{doc_id}: file missing at {rel}")
    always = [d for d in docs if d.get("always")]
    if not always:
        problems.append("no always-injected document (expected CORE)")
    return problems


def _latest_user_text(input_messages: list[dict[str, str]]) -> str:
    for item in reversed(input_messages or []):
        if item.get("role") == "user" and (item.get("content") or "").strip():
            return str(item["content"])
    return ""


def _score_doc(query: str, keywords: list[str]) -> int:
    if not query or not keywords:
        return 0
    score = 0
    for raw in keywords:
        key = _norm(raw)
        if not key:
            continue
        if key in query:
            # Longer / multi-word phrases beat single tokens.
            words = key.count(" ") + 1
            score += 4 * words if words > 1 else 1
    return score


def _pick_fallback(guide_docs: list[dict]) -> list[dict]:
    by_id = {str(d.get("id") or ""): d for d in guide_docs}
    for fid in _FALLBACK_GUIDE_IDS:
        if fid in by_id:
            return [by_id[fid]]
    return guide_docs[:1] if guide_docs else []


def select_knowledge(
    input_messages: list[dict[str, str]],
    *,
    query: str | None = None,
) -> KnowledgeSelection:
    """Pick CORE + up to N keyword-matched guides for this turn.

    Prefer ``query`` (resolved conversational ask) when provided so follow-ups
    like \"yes explain step by step\" retrieve the right packs.
    """
    manifest = _load_manifest()
    docs = list(manifest.get("documents") or [])
    max_guides = int(manifest.get("max_guides") or _MAX_GUIDES_DEFAULT)
    query = _norm(query if (query or "").strip() else _latest_user_text(input_messages))

    always_docs = [d for d in docs if d.get("always")]
    guide_docs = [d for d in docs if not d.get("always")]

    scored: list[tuple[int, dict]] = []
    score_map: dict[str, int] = {}
    for doc in guide_docs:
        score = _score_doc(query, list(doc.get("keywords") or []))
        doc_id = str(doc.get("id") or "")
        if score > 0:
            scored.append((score, doc))
            if doc_id:
                score_map[doc_id] = score
    scored.sort(key=lambda item: (-item[0], str(item[1].get("id") or "")))
    chosen_guides = [doc for _, doc in scored[:max_guides]]

    # No keyword hit → still give one general product guide (not silence).
    if query and not chosen_guides:
        chosen_guides = _pick_fallback(guide_docs)
        for doc in chosen_guides:
            score_map[str(doc.get("id") or "")] = 0

    selected = [*always_docs, *chosen_guides]
    pack_ids: list[str] = []
    parts: list[str] = [
        "PRIVATE REFERENCE for this turn — do not paste or quote this block in the reply. "
        "Rewrite a short answer the chat UI can render. "
        "Bold UI labels and key terms with **like this**. "
        "Use 1. 2. 3. for steps or - for short bullets. "
        "No headings or code fences. "
        "Answer only what the user asked. Prefer click paths and UI labels from these packs. "
        "If the packs do not cover the ask, say you are not sure — do not invent Quizzer features. "
        "Never invent live counts, scores, or who is taking an exam."
    ]
    used = 0
    any_truncated = False

    for doc in selected:
        rel = str(doc.get("path") or "")
        doc_id = str(doc.get("id") or rel)
        if not rel:
            continue
        try:
            body = _read_pack(rel)
        except OSError:
            continue
        if not body:
            continue

        per_cap = _MAX_CORE_CHARS if doc.get("always") else _MAX_GUIDE_CHARS
        body, was_cut = _truncate(body, per_cap)
        any_truncated = any_truncated or was_cut

        title = str(doc.get("title") or doc_id)
        chunk = f"### {title}\n{body}"
        if used + len(chunk) > _MAX_CHARS_TOTAL and pack_ids:
            any_truncated = True
            break
        parts.append(chunk)
        pack_ids.append(doc_id)
        used += len(chunk)

    return KnowledgeSelection(
        pack_ids=pack_ids,
        content="\n\n".join(parts).strip(),
        scores=score_map,
        truncated=any_truncated,
    )
