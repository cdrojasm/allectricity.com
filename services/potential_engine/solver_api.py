"""Entrypoint for the standalone solver service.

The compiled solver is loaded from ``SPAT_POTENTIAL_ENGINE`` and each request
executes one complete project calculation in an isolated child process. The
HTTP protocol intentionally carries the solver's existing text protocol so
results remain byte-for-byte compatible with local calculations.
"""

import os
import shutil
import socket

from server import Handler, ThreadingHTTPServer


def main() -> None:
    engine = os.getenv("SPAT_POTENTIAL_ENGINE", "/usr/local/bin/spat-potential-engine")
    if not shutil.which(engine) and not os.path.isfile(engine):
        raise RuntimeError(f"solver binary not found: {engine}")
    host = os.getenv("BIND_HOST", "0.0.0.0")
    server_class = ThreadingHTTPServer
    if ":" in host:  # IPv6 (e.g. "::" on Railway's private network), dual-stack where the OS allows it
        server_class = type("ThreadingHTTPServerV6", (ThreadingHTTPServer,), {"address_family": socket.AF_INET6})
    server_class((host, int(os.getenv("PORT", "8080"))), Handler).serve_forever()


if __name__ == "__main__":
    main()
