"""MCP server exposing Koi's sessions and modules to an MCP client.

The server itself lives in :mod:`koi.mcp.server` and requires the optional
``mcp`` dependency (``pipx install 'koi-handler[mcp]'``). Importing this package
does not pull it in, so ``koi.mcp.schema`` stays usable on a bare install.
"""
