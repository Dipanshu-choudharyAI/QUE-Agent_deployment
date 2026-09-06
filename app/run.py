"""Local/dev entrypoint: `uv run python -m app.run`."""

import uvicorn

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.is_local,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
