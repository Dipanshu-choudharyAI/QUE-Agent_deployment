"""Unit tests for section-aware knowledge chunking (no LLM / Chroma)."""

from __future__ import annotations

from app.knowledge.chunking import chunk_markdown, strip_frontmatter


def test_strip_frontmatter():
    raw = "---\ntitle: x\n---\n\n# Hello\nBody"
    assert strip_frontmatter(raw).startswith("# Hello")


def test_chunks_by_heading():
    md = """---
id: demo
---

# Title

Intro paragraph about the product.

## Create exam

Click **Create Exam** in the sidebar.

## Publish

Use **Publish** when questions are approved.
"""
    chunks = chunk_markdown(
        doc_id="demo",
        path="demo.md",
        title="Demo",
        raw_markdown=md,
        corpus_version="1.0.0",
    )
    assert len(chunks) >= 2
    sections = {c.section for c in chunks}
    assert "Create exam" in sections or any("Create" in c.section for c in chunks)
    assert all(c.doc_id == "demo" for c in chunks)
    assert all(c.content_hash for c in chunks)
    assert all(c.corpus_version == "1.0.0" for c in chunks)


def test_oversized_section_splits():
    long_body = "Paragraph about Quizzer.\n\n" * 80
    md = f"## Huge section\n\n{long_body}"
    chunks = chunk_markdown(
        doc_id="big",
        path="big.md",
        title="Big",
        raw_markdown=md,
        corpus_version="1",
        max_chars=400,
        overlap_chars=40,
    )
    assert len(chunks) >= 2
    assert all(c.char_count <= 450 for c in chunks)
