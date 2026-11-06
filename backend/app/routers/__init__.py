"""HTTP routers: domain endpoints split out of ``main.py`` (Phase 1).

``main.py`` keeps app assembly only (FastAPI(), CORS, middleware, exception
handlers, static mount). Route paths, status codes and payload shapes are
byte-identical to the pre-split behaviour — ``scripts/api_contract.mjs`` and
``scripts/safety_audit.mjs`` (Part B) verify exactly that.
"""
