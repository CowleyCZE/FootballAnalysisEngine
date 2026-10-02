from fastapi import FastAPI
from app.orchestrator.router import router as orchestrator_router

app = FastAPI(title="Football Research Orchestrator")

# Připojení routeru
app.include_router(orchestrator_router)