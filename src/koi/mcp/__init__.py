"""MCP server exposing Koi's sessions and modules to an MCP client.

The server lives in :mod:`koi.mcp.server`. Its dependencies (mcp, uvicorn,
starlette) ship with core as of 0.11, so ``--mcp`` works on any install. They
are still imported lazily, only when the server starts, to keep ``koi`` startup
free of them on the common no-MCP path; the server itself stays off until the
flag or config enables it.
"""
