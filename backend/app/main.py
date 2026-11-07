"""MedRecall FastAPI application — assembly only (Phase 1, Phase 2).

Endpoints
---------
POST   /api/auth/otp/request                     request a phone OTP (dev echoes the code)
POST   /api/auth/otp/verify                      verify OTP -> access token + refresh cookie
POST   /api/auth/refresh                         rotate the refresh token (cookie)
POST   /api/auth/logout                          end the session (cookie)
GET    /api/patients/me                          own profile
PATCH  /api/patients/me                          update own profile (lang/timezone/caregiver)
GET    /api/patients/me/consent                  own per-channel communication consent
POST   /api/patients/me/consent                  grant/revoke consent for a channel
GET    /api/prescriptions                        own prescriptions, newest first
POST   /api/prescriptions                        upload image/PDF -> OCR -> items
GET    /api/prescriptions/{id}                   fetch for the review screen (own only)
PATCH  /api/prescriptions/{id}/items/{item_id}   confirm / edit an unclear item
POST   /api/prescriptions/{id}/schedule?lang=... timetable (clear/confirmed/edited only)
GET    /api/prescriptions/{id}/timetable.pdf     printable PDF
GET    /api/prescriptions/{id}/reminders?lang=... reminder feed (display only)
POST   /api/prescriptions/{id}/reminders/enroll    start reminders from the verified timetable
DELETE /api/prescriptions/{id}/reminders/enroll    stop reminders (history kept)
GET    /api/reminders/upcoming                     next occurrences (patient-local times)
POST   /api/reminders/run                          one manual generate+dispatch tick
GET    /api/reminders/history                      sent / blocked / missed occurrences
GET    /api/health                               OCR availability check
POST   /api/demo                                 prefilled prescription (no OCR)
GET    /uploads/{filename}?exp=..&sig=..         signed, expiring image URL (15 min)

Route handlers live in ``app/routers/`` (``auth.py``, ``patients.py``,
``prescriptions.py``, ``reminders.py``, ``system.py``); this module wires the
app together: settings, logging, CORS, request-ID middleware, exception
handlers, the reminder dispatcher lifespan and ``init_db()``.

Auth (Phase 2): every /api/* route except /api/health and the /api/auth
login routes requires a Bearer access token; prescriptions are scoped to
the caller (someone else's id -> 404, no existence leak). Uploaded images
are no longer served by a public static mount — only via signed URLs.

Reminders (Phase 3): the background dispatcher is started by the lifespan
(``MEDRECALL_REMINDER_DISPATCHER=off`` disables it; tests do that). It only
ever sends items that are still scheduleable and not SOS/PRN, inside the
grace window, and only to a channel the patient explicitly consented to.

THE SAFETY RULE: unclear items are never translated, scheduled, printed or
used for reminders — see uncertainty.SCHEDULEABLE_STATUSES; the only status
transitions are in routers/prescriptions.py::patch_item (gated: confirm/edit
can produce confirmed/edited/unclear, never a fresh "clear").
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import DISCLAIMER, __version__
from .core.config import UPLOAD_DIR, get_settings
from .core.logging import setup_logging
from .core.middleware import RequestContextMiddleware
from .db import init_db
from .ocr import OcrError
from .reminders import dispatcher_loop
from .routers import auth, patients, prescriptions, reminders, system
from .translate import TranslationError, UnsupportedLanguageError

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

settings = get_settings()
setup_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Run the reminder dispatcher for the app's lifetime (tests disable it)."""
    task: asyncio.Task | None = None
    if settings.reminder_dispatcher:
        task = asyncio.create_task(
            dispatcher_loop(settings.reminder_interval_seconds)
        )
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(
    title="MedRecall API",
    description="Making medicine instructions simple, safe and understandable. " + DISCLAIMER,
    version=__version__,
    lifespan=lifespan,
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
# NOTE (Phase 2): the public StaticFiles mount for /uploads is intentionally
# gone — images are served by routers/prescriptions.py::get_prescription_image
# through signed, 15-minute expiring URLs (core.security.sign_image_url).

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

app.include_router(auth.router)
app.include_router(patients.router)
app.include_router(prescriptions.router)
app.include_router(reminders.router)
app.include_router(system.router)
