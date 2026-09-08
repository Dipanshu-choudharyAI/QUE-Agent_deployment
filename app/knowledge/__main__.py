"""Allow ``python -m app.knowledge`` as an alias for build_index."""

from app.knowledge.build_index import main

raise SystemExit(main())
