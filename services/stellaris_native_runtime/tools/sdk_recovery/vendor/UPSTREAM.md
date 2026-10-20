# Upstream attribution

The Python files in this directory, including the historical token table, are
adapted from `Yidhar/stellaris-mcp`, commit
`6cc8e82013f88d7ef51d906f3cdfa44054b7a250`, `tools/sdk_dumper/`.

Copyright (c) 2026 Yidhar. These files remain MIT-licensed; the complete
upstream license is retained in `LICENSE`.

OGAS changes provide explicit input/output paths and current Linux ELF symbol
associations. The original decompile indexer and historical token map are kept
as optional reference inputs; the default workflow extracts the current Linux
binary directly. No upstream hook, bridge runtime, execution queue, MCP server
or action manager is imported.
