from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import (
    analysis, auth, builder, export, files, matching,
    navigate, payments, extension, webhook, discovery, first_resume, jobs,
    ats_shield, analytics, models, templates, interview, resume_defense,
)

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(analysis.router, prefix=settings.api_prefix)
app.include_router(matching.router, prefix=settings.api_prefix)
app.include_router(builder.router, prefix=settings.api_prefix)
app.include_router(export.router, prefix=settings.api_prefix)
app.include_router(files.router, prefix=settings.api_prefix)
app.include_router(payments.router, prefix=settings.api_prefix)
app.include_router(extension.router, prefix=settings.api_prefix)
app.include_router(webhook.router, prefix=settings.api_prefix)
app.include_router(discovery.router, prefix=settings.api_prefix)
app.include_router(first_resume.router, prefix=settings.api_prefix)
app.include_router(navigate.router, prefix=settings.api_prefix)
app.include_router(jobs.router, prefix=settings.api_prefix)
app.include_router(ats_shield.router, prefix=settings.api_prefix)
app.include_router(analytics.router, prefix=settings.api_prefix)
app.include_router(models.router, prefix=settings.api_prefix)
app.include_router(templates.router, prefix=settings.api_prefix)
app.include_router(interview.router, prefix=settings.api_prefix)

app.include_router(resume_defense.router, prefix=settings.api_prefix)

