from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.config import settings
from app.database import engine, Base
from app.api.routes import auth, upload, jobs, payments

Base.metadata.create_all(bind=engine)

# Add any columns that were introduced after the initial table creation
def _migrate():
    new_cols = [
        ("billing_cycle",           "VARCHAR(20) DEFAULT 'monthly'"),
        ("period_end",              "DATETIME NULL"),
        ("stripe_customer_id",      "VARCHAR(100) NULL"),
        ("stripe_subscription_id",  "VARCHAR(100) NULL"),
        ("totp_secret",             "VARCHAR(64) NULL"),
        ("is_2fa_enabled",          "BOOLEAN DEFAULT FALSE"),
        ("is_email_verified",       "BOOLEAN DEFAULT FALSE"),
        ("email_otp_hash",          "VARCHAR(64) NULL"),
        ("otp_expires_at",          "DATETIME NULL"),
    ]
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SHOW COLUMNS FROM users")).fetchall()
            existing = {r[0] for r in rows}
            for col, defn in new_cols:
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {defn}"))
            conn.commit()
    except Exception as exc:  # table may not exist yet on very first boot
        print(f"[migration] skipped: {exc}")

_migrate()

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Enterprise data cleaning SaaS — async, chunked, multi-worker",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(upload.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(payments.router, prefix="/api/v1")


@app.get("/")
def root():
    return {"name": settings.APP_NAME, "status": "running", "version": "1.0.0"}


@app.get("/health")
def health():
    return {"status": "healthy"}
