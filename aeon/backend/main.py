from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from api import pipelines, incidents, github, jenkins, n8n, ai, memory, integrations, actions, odysseus, provenance, blast_radius, cochange


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Aeon backend started")
    yield


app = FastAPI(
    title="Aeon API",
    description="AI-powered engineering operations workspace",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "aeon"}


app.include_router(pipelines.router, prefix="/api")
app.include_router(incidents.router, prefix="/api")
app.include_router(github.router, prefix="/api")
app.include_router(jenkins.router, prefix="/api")
app.include_router(n8n.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(memory.router, prefix="/api")
app.include_router(integrations.router, prefix="/api")
app.include_router(actions.router, prefix="/api")
app.include_router(odysseus.router, prefix="/api")
app.include_router(provenance.router, prefix="/api")
app.include_router(blast_radius.router, prefix="/api")
app.include_router(cochange.router, prefix="/api")
