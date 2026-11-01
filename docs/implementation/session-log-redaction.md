# WebSocket session query log redaction

Uvicorn can log a WebSocket URL through `uvicorn.error` at INFO even when access
logging is disabled. API startup now installs one idempotent filter on each of
`uvicorn.error` and `uvicorn.access`. Their levels, handlers, formatters and global
LogRecordFactory remain unchanged.

The filter sanitizes actual `LogRecord.msg` and `args`, including mapping arguments,
literal URLs, template-assembled URLs, repeated query fields and encoded session
keys. The normal five access arguments remain available to AccessFormatter.
Exception/stack text and API structured log output receive the same redaction.
Request data and authentication behavior are unchanged; useful paths, event names,
status codes and unrelated debug parameters remain visible.

Tests use only synthetic credentials, actual logging records, the real Uvicorn
AccessFormatter, captured API JSON output and an isolated startup import. No real
user session or running user service is read or modified.
