"""MedRecall FastAPI application — assembly only (Phase 1).

Endpoints
---------
POST   /api/prescriptions                          upload image/PDF -> OCR -> items
GET    /api/prescriptions/{id}                     fetch for the review screen
PATCH  /api/prescriptions/{id}/items/{item_id}     confirm / edit an unclear item
POST   /api/prescriptions/{id}/schedule?lang=...   timetable (clear/confirmed/edited only)
GET    /api/prescriptions/{id}/timetable.pdf       printable PDF
GET    /api/prescriptions/{id}/reminders?lang=...  reminder feed
GET    /api/health                                 OCR availability check
POST   /api/demo                                   prefilled prescription (no OCR)

Route handlers live in ``app/routers/`` (``prescriptions.py``, ``system.py``);
this module wires the app together: settings, logging, CORS, request-ID
middleware, exception handlers, static uploads and ``init_db()``.

THE SAFETY RULE: unclear items are never translated, scheduled, printed or
used for reminders — see uncertainty.SCHEDULEABLE_STATUSES; the only status
transitions are in routers/prescriptions.py::patch_item (gated: confirm/edit
can produce confirmed/edited/unclear, never a fresh "clear").
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import DISCLAIMER, __version__
from .core.config import UPLOAD_DIR, get_settings
from .core.logging import setup_logging
from .core.middleware import RequestContextMiddleware
from .db import init_db
from .ocr import OcrError
from .routers import prescriptions, system
from .translate import TranslationError, UnsupportedLanguageError

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

settings = get_settings()
setup_logging(settings.log_level)

app = FastAPI(
    title="MedRecall API",
    description="Making medicine instructions simple, safe and understandable. " + DISCLAIMER,
    version=__version__,
)

# Outermost: assign X-Request-ID + access logs to every request (incl. CORS preflight).
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

init_db()  # create tables on import (idempotent)


# ---------------------------------------------------------------------------
# Clean JSON errors
# ---------------------------------------------------------------------------


@app.exception_handler(OcrError)
async def _ocr_error_handler(request, exc: OcrError):  # noqa: ARG001
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(TranslationError)
async def _translation_error_handler(request, exc: TranslationError):  # noqa: ARG001
    status = 400 if isinstance(exc, UnsupportedLanguageError) else 500
    return JSONResponse(status_code=status, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

app.include_router(prescriptions.router)
app.include_router(system.router)
