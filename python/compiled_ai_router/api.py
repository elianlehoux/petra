import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from .models import TaskRequest, TaskResponse, MetricsSummary
from .router import CompiledAIRouter
from .config import settings

app = FastAPI(title="Compiled AI Router API")

# allow_origins=["*"] junto con allow_credentials=True es inválido/inseguro.
# La UI se sirve del mismo origen, así que no hacen falta credenciales cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

router = CompiledAIRouter(settings)

# UI Directory path
UI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "ui"))

@app.post("/route", response_model=TaskResponse)
async def route_task(request: TaskRequest):
    try:
        return await router.route(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/metrics", response_model=MetricsSummary)
def get_metrics():
    return router.get_metrics()

@app.get("/artifacts")
def list_artifacts():
    return list(router.artifacts.values())

@app.get("/artifacts/{id}")
def get_artifact(id: str):
    if id not in router.artifacts:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return router.artifacts[id]

@app.delete("/artifacts/{id}")
def delete_artifact(id: str):
    if id in router.artifacts:
        del router.artifacts[id]
        path = os.path.join(settings.ARTIFACT_DIR, f"{id}.json")
        if os.path.exists(path):
            os.remove(path)
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Artifact not found")

@app.post("/compile", response_model=TaskResponse)
async def force_compile(request: TaskRequest):
    request.force_compile = True
    return await route_task(request)

@app.post("/execute/{id}")
def execute_artifact(id: str, input_data: dict = None):
    if id not in router.artifacts:
        raise HTTPException(status_code=404, detail="Artifact not found")
    artifact = router.artifacts[id]
    output, duration, success = router.execute_artifact(artifact, input_data)
    return {"output": output, "duration_ms": duration, "success": success}

@app.get("/health")
def health():
    return {"status": "ok"}

# Mount UI static files directly at root so index.html, styles.css, and app.js resolve seamlessly
if os.path.exists(UI_DIR):
    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
