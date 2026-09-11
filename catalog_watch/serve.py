"""A local static server for the bundled fixture storefront.

This exists so the demo scrapes over real HTTP — same fetch path, same
robots.txt check, same pagination — without pointing at anybody's live site.
It binds port 0 on the loopback interface, so runs never collide and nothing is
reachable from outside the machine.

``watch.py --serve fixtures/site`` uses this. ``watch.py https://...`` does not
go anywhere near it.
"""

from __future__ import annotations

import contextlib
import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # noqa: D102 - stdlib hook
        pass


@contextlib.contextmanager
def serve_directory(directory: str | Path, port: int = 0):
    """Serve ``directory`` on 127.0.0.1 for the duration of the block.

    Yields the base URL, e.g. ``http://127.0.0.1:41725/``.
    """
    root = Path(directory).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"no such directory to serve: {root}")

    handler = functools.partial(_QuietHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main(argv: list[str] | None = None) -> int:
    """``python -m catalog_watch.serve <dir> [--port N]`` — handy for poking at
    the fixture in a browser."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    with serve_directory(args.directory, args.port) as base_url:
        print(f"serving {args.directory} at {base_url}  (ctrl-c to stop)")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
