import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import init_db
from app.services.file_service import file_service
from app.api.v1.api import api_router

from app.core.middleware import CorrelationIdMiddleware, CorrelationIdFilter

# Setup logging with Correlation ID injection
log_handler = logging.StreamHandler()
log_handler.setFormatter(
    logging.Formatter("%(asctime)s - [%(correlation_id)s] - %(name)s - %(levelname)s - %(message)s")
)
log_handler.addFilter(CorrelationIdFilter())

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.handlers = [log_handler]

logger = logging.getLogger("ingestify")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle management."""
    logger.info("Starting up Ingestify engine...")
    file_service.ensure_directories()
    try:
        init_db()
        logger.info("Database schema verified.")
    except Exception as e:
        logger.warning(f"Database connection deferred or pending: {e}")
    yield
    logger.info("Shutting down Ingestify engine...")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.PROJECT_DESCRIPTION,
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,  # Custom ReDoc route defined below with stable ReDoc bundle
    openapi_url="/openapi.json",
)

# Cross-Origin Resource Sharing (CORS) Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)

# Request Tracing & Correlation ID Middleware
app.add_middleware(CorrelationIdMiddleware)


# Mount local application static directory (e.g. self-hosted clean redoc bundle)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Serve generated thumbnails and artifacts as static assets
if os.path.exists(settings.STORAGE_BASE_DIR):
    app.mount("/storage", StaticFiles(directory=settings.STORAGE_BASE_DIR), name="storage")

# Mount API v1 router
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/redoc", response_class=HTMLResponse, include_in_schema=False)
def custom_redoc_html():
    """Enterprise customized ReDoc documentation rendered via local clean Redoc bundle."""
    # Use locally hosted clean redoc bundle if available, otherwise fallback to cdn
    script_src = "/static/redoc.standalone.js" if os.path.exists(os.path.join(static_dir, "redoc.standalone.js")) else "https://cdn.jsdelivr.net/npm/redoc@2.1.5/bundles/redoc.standalone.js"

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <title>{settings.PROJECT_NAME} — API Documentation (ReDoc)</title>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="shortcut icon" href="https://fastapi.tiangolo.com/img/favicon.png">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    body {{
      margin: 0;
      padding: 0;
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #ffffff;
    }}
    #redoc-container {{
      min-height: 100vh;
    }}
    .loading {{
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 80vh;
      color: #4b5563;
      font-size: 15px;
    }}
    .spinner {{
      border: 3px solid rgba(0, 0, 0, 0.08);
      width: 40px;
      height: 40px;
      border-radius: 50%;
      border-left-color: #2563eb;
      animation: spin 0.8s linear infinite;
      margin-bottom: 16px;
    }}
    @keyframes spin {{
      0% {{ transform: rotate(0deg); }}
      100% {{ transform: rotate(360deg); }}
    }}
  </style>
</head>
<body>
  <div id="redoc-container">
    <div class="loading">
      <div class="spinner"></div>
      <div>Loading Ingestify API Specification...</div>
    </div>
  </div>
  <script src="{script_src}"></script>
  <script>
    window.addEventListener('DOMContentLoaded', function() {{
      Redoc.init(
        '{app.openapi_url}',
        {{
          scrollYOffset: 0,
          hideDownloadButton: false,
          expandResponses: '200,201,202',
          requiredPropsFirst: true,
          theme: {{
            colors: {{
              primary: {{ main: '#2563eb' }},
              success: {{ main: '#10b981' }},
              warning: {{ main: '#f59e0b' }},
              error: {{ main: '#ef4444' }}
            }},
            typography: {{
              fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
              headings: {{ fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif", fontWeight: '600' }},
              code: {{ fontFamily: "'JetBrains Mono', monospace" }}
            }},
            sidebar: {{
              backgroundColor: '#0f172a',
              textColor: '#e2e8f0',
              activeTextColor: '#38bdf8',
              width: '280px'
            }}
          }}
        }},
        document.getElementById('redoc-container')
      );
    }});
  </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)


@app.get("/{path:path}.map", include_in_schema=False)
def sourcemap_fallback(path: str):
    """Fallback handler returning clean, valid dummy sourcemaps for browser DevTools."""
    return JSONResponse(
        content={"version": 3, "file": f"{path}.js", "sources": [], "mappings": ""},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Content-Type": "application/json",
        },
    )


@app.get("/", tags=["System"])
def root():
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "description": settings.PROJECT_DESCRIPTION,
        "documentation": "/docs",
        "redoc": "/redoc",
        "health": "/health_check",
    }


@app.get("/health_check", tags=["System"])
def health_check():
    """Liveness probe for orchestration and load balancers."""
    return {
        "status": "healthy",
        "service": "Ingestify Core API",
        "version": settings.VERSION,
    }
