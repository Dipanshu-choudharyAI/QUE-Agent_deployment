"""CLI: ``python -m app.knowledge.build_index`` — build/update Chroma index."""

from __future__ import annotations

import argparse
import json
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build or incrementally update the QUE knowledge Chroma index.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Wipe and re-embed every document (also used when embedding model changes).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print IngestReport as JSON.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    from app.knowledge.ingest import build_index

    report = build_index(force=args.force)
    if args.json:
        print(json.dumps(report.__dict__, indent=2))
    else:
        print(
            f"Index ready — docs={report.docs_total} "
            f"upserted={report.docs_upserted} unchanged={report.docs_unchanged} "
            f"deleted_chunks={report.docs_deleted} chunks_written={report.chunks_upserted} "
            f"model={report.embedding_model} corpus={report.corpus_version} "
            f"rebuilt={report.rebuilt}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
