# QUE build progress (handbook-aligned)

Open the interactive tracker: [`que-agent-handbook.html`](que-agent-handbook.html).

## Current focus: Phase 2 knowledge wired end-to-end

| Phase | Status | Notes |
|---|---|---|
| 0 Foundations | Done | Separate microservice, JWT/service-key auth |
| 1 QUE Core + understanding + evals | Done (this repo) | Request Understanding + golden scope eval |
| 2 Knowledge + basic RAG | **In progress — keyword KB v3 live** | 28 docs via `manifest.json`; no embeddings yet |
| 3+ Context / tools / … | Not started | Next high value: Phase 4 tools |

## Knowledge slice (2026-09-06)

- `app/knowledge/retrieve.py` loads the new domain folders from `knowledge/manifest.json`
- Strips YAML frontmatter, caps CORE/guide size, selects up to `max_guides` (3)
- Fallback guide when no keywords match (`lifecycle` → `common-workflows` → `product-overview`)
- Startup validates every manifest path exists
- Chat/SSE responses expose `knowledge_packs` (+ scores in SSE meta)
