#!/usr/bin/env python
"""Start the experiment server.

    python run.py                 # development server, auto-reload, debug pages
    python run.py --production    # gunicorn, what you run for real participants

This replaces `psiturk server on` / `psiturk debug`.
"""

import argparse
import os
import sys

from server import create_app
from server.config import get_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", help="Interface to bind (default from config.ini)")
    parser.add_argument("--port", type=int, help="Port to bind (default from config.ini)")
    parser.add_argument(
        "--production",
        action="store_true",
        help="Serve with gunicorn instead of the Flask development server",
    )
    args = parser.parse_args()

    config = get_config()
    host = args.host or config.get("Server Parameters", "host", "127.0.0.1")
    port = args.port or config.get_int("Server Parameters", "port", 22362)

    if args.production:
        # Re-exec into gunicorn so it manages the workers itself.
        workers = config.get_int("Server Parameters", "workers", 2)
        threads = config.get_int("Server Parameters", "threads", 4)
        argv = [
            "gunicorn",
            "--bind",
            f"{host}:{port}",
            "--workers",
            str(workers),
            "--threads",
            str(threads),
            "--timeout",
            "60",
            "--access-logfile",
            "-",
            "wsgi:app",
        ]
        certfile = config.get("Server Parameters", "certfile")
        keyfile = config.get("Server Parameters", "keyfile")
        if certfile and keyfile:
            argv += ["--certfile", certfile, "--keyfile", keyfile]

        os.execvp("gunicorn", argv)

    app = create_app(config)

    # 0.0.0.0 is a valid bind address but not a URL you can click.
    display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    print(f"\n  Consent page:  http://{display_host}:{port}/consent")
    print(f"  Debug run:     http://{display_host}:{port}/exp")
    print(f"  Status:        http://{display_host}:{port}/admin/status\n")
    app.run(host=host, port=port, debug=True, use_reloader=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
