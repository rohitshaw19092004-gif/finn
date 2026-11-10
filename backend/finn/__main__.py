"""CLI.

  python -m finn refresh              daily job -> web/public/data
  python -m finn research DIXON       one dossier to stdout (any NSE symbol on screener)
  python -m finn serve                API for live Pull (uvicorn)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="finn")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("refresh")
    r = sub.add_parser("research")
    r.add_argument("symbol")
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8000)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)      # one line per request drowned the real problems

    if a.cmd == "refresh":
        from .snapshot import build
        meta = build()
        run = meta["run"]
        print(json.dumps({k: meta[k] for k in ("generated_at", "as_of", "filings", "stories", "models")}, indent=1))
        print(json.dumps({"health": run["health"], "warnings": run["warnings"], "research": run["research"],
                          "documents": run["documents"], "llm_totals": meta["llm"]["totals"],
                          "llm_models": meta["llm"]["models"]}, indent=1, ensure_ascii=False))
        if run["health"] == "failed":
            print("Refresh FAILED: core data sources are missing; the snapshot will not be committed.", file=sys.stderr)
            return 1
    elif a.cmd == "research":
        from .intel.research import build
        d = build(a.symbol, progress=lambda step, msg: print(f"· {msg}", file=sys.stderr))
        print(json.dumps(d, indent=1, ensure_ascii=False))
    elif a.cmd == "serve":
        import uvicorn
        uvicorn.run("finn.api:app", host="0.0.0.0", port=a.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
