from app.api.server import app
from app.orchestrator.router import router as orchestrator_router

# Připojení routeru k hlavní FastAPI aplikaci
app.include_router(orchestrator_router)
