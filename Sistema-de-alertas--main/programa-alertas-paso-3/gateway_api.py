from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config import settings
from database import Database
from gateway_config import load_gateway_config, token_valid
from gateway_store import GatewayStore, QueueError


class Heartbeat(BaseModel):
    active: bool
    sim_label: str = Field(default="",max_length=100)


class Start(BaseModel):
    ticket: str = Field(min_length=36,max_length=36)


class Report(Start):
    revision: int = Field(ge=1,le=100000)
    state: Literal["UNKNOWN","SUBMITTED","SENT","FAILED"]
    delivery: Literal["WAITING","DELIVERED","FAILED","UNKNOWN"]
    detail: str = Field(default="",max_length=250)


def create_api(config=None, store=None):
    config=config or load_gateway_config(required=True)
    store=store or GatewayStore(settings.database_path,config["allowed_numbers"])

    @asynccontextmanager
    async def lifespan(app):
        Database(store.path).initialize()
        store.initialize()
        yield

    api=FastAPI(title="Gateway privado",lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)

    @api.middleware("http")
    async def authenticate(request: Request, call_next):
        if request.url.scheme != "https":
            return JSONResponse({"detail":"Se requiere HTTPS"},status_code=403)
        authorization=request.headers.get("authorization","")
        token=authorization[7:] if authorization.startswith("Bearer ") else ""
        if not token_valid(config,token):
            return JSONResponse({"detail":"Credencial inválida o vencida"},status_code=401)
        device=request.headers.get("x-gateway-device","")
        try:
            import uuid
            if str(uuid.UUID(device)) != device:
                raise ValueError()
        except ValueError:
            return JSONResponse({"detail":"Dispositivo inválido"},status_code=400)
        request.state.device=device
        response=await call_next(request)
        response.headers["Cache-Control"]="no-store"
        return response

    @api.exception_handler(QueueError)
    async def queue_error(request, error):
        return JSONResponse({"detail":str(error)},status_code=409)

    @api.post("/api/gateway/heartbeat")
    def heartbeat(payload: Heartbeat, request: Request):
        return store.heartbeat(request.state.device,payload.active,payload.sim_label)

    @api.post("/api/gateway/jobs/next")
    def next_job(request: Request):
        return {"job":store.next_job(request.state.device)}

    @api.post("/api/gateway/jobs/{job_id}/start")
    def start(job_id: str,payload: Start,request: Request):
        return store.start(request.state.device,job_id,payload.ticket)

    @api.post("/api/gateway/jobs/{job_id}/report")
    def report(job_id: str,payload: Report,request: Request):
        return store.report(request.state.device,job_id,payload.ticket,payload.revision,
                            payload.state,payload.delivery,payload.detail)

    return api


def app_factory():
    return create_api()
