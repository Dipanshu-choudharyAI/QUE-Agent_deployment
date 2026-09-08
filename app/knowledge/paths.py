"""Filesystem roots for QUE product knowledge packs."""

from __future__ import annotations

from pathlib import Path

KNOWLEDGE_ROOT = Path(__file__).resolve().parents[2] / "knowledge"
MANIFEST_PATH = KNOWLEDGE_ROOT / "manifest.json"
