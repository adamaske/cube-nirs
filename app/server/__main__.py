"""`python -m app.server` — serve the session GUI on http://localhost:8765/"""
import argparse

import uvicorn

from app.server.main import create_app


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args()
    print(f"Control panel:   http://{args.host}:{args.port}/")
    print(f"Subject display: http://{args.host}:{args.port}/subject   (F11 on monitor 2)")
    print(f"Dashboard:       http://{args.host}:{args.port}/dashboard")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
