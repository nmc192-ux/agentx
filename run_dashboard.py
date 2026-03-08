#!/usr/bin/env python3
"""
AgentX — Live Dashboard
════════════════════════
Starts the AgentX web dashboard at http://localhost:8000
and opens it in your browser automatically.

Usage:
  python3 run_dashboard.py            # Default: port 8000
  python3 run_dashboard.py --port 9000
  python3 run_dashboard.py --no-browser  # Don't open browser automatically
"""
import argparse
import sys
import time
import webbrowser
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(description="AgentX Live Dashboard")
    p.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    p.add_argument("--host", type=str, default="127.0.0.1", help="Host (default: 127.0.0.1)")
    p.add_argument("--no-browser", action="store_true", help="Don't open browser automatically")
    return p.parse_args()


def main():
    args = parse_args()

    # Check dependencies
    try:
        import fastapi  # noqa
        import uvicorn  # noqa
    except ImportError:
        print("\n  ❌ Missing dependencies. Install with:")
        print("     pip install fastapi uvicorn[standard] watchfiles\n")
        sys.exit(1)

    url = f"http://{args.host}:{args.port}"

    print("\n╔══════════════════════════════════════════════════════════════════════╗")
    print("║  🏛️  AgentX — Live Dashboard                                         ║")
    print("╠══════════════════════════════════════════════════════════════════════╣")
    print(f"║  URL     : {url:<59}║")
    print(f"║  Host    : {args.host:<59}║")
    print(f"║  Port    : {args.port:<59}║")
    print("╠══════════════════════════════════════════════════════════════════════╣")
    print("║  Keep this terminal open while using the dashboard.                  ║")
    print("║  Press Ctrl+C to stop the server.                                    ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")
    print()

    # Open browser after a short delay
    if not args.no_browser:
        import threading
        def open_browser():
            time.sleep(1.5)
            webbrowser.open(url)
        threading.Thread(target=open_browser, daemon=True).start()
        print(f"  → Opening browser at {url}\n")

    import sys
    sys.path.insert(0, str(Path(__file__).parent))

    import uvicorn
    uvicorn.run(
        "dashboard.server:app",
        host     = args.host,
        port     = args.port,
        reload   = False,
        log_level = "warning",  # suppress noisy access logs
    )


if __name__ == "__main__":
    main()
