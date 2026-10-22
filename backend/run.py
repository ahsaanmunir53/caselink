"""Start the API locally.

    python run.py              # http://127.0.0.1:8000
    python run.py --reload     # restart on code changes

Works the same on Windows, macOS and Linux. (On Windows the Postgres driver needs a selector
event loop, which plain `uvicorn app.main:app` without --reload does not use.)
"""

import argparse

import uvicorn

from app.core.aio import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the CaseLink API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="restart when code changes")
    args = parser.parse_args()

    if args.reload:
        # uvicorn runs the reloading server in a subprocess, which already uses a selector loop.
        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=True)
        return
    server = uvicorn.Server(uvicorn.Config("app.main:app", host=args.host, port=args.port))
    run(server.serve())


if __name__ == "__main__":
    main()
