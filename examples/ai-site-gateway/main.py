"""Runnable site backend. Replace require_visitor with your site's session check."""

import secrets
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    ARK_AI_BASE_URL: str
    ARK_AI_KEY: str
    ARK_AI_PRESET: str
    SITE_VISITOR_TOKEN: str = Field(min_length=32)


class GenerateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=16000)


def create_app(settings: Settings, transport=None):
    app = FastAPI(title='Site AI example')

    def require_visitor(authorization: str | None = Header(None)):
        # Demo invitation credential only. Integrate real login/session validation
        # here before exposing the site to visitors. Never use ARK_AI_KEY here.
        expected = 'Bearer ' + settings.SITE_VISITOR_TOKEN
        if not authorization or not secrets.compare_digest(authorization, expected):
            raise HTTPException(401, 'Please sign in to this site')

    @app.post('/generate', dependencies=[Depends(require_visitor)])
    async def generate(data: GenerateRequest):
        request_id = str(uuid4())
        headers = {'Authorization': f'Bearer {settings.ARK_AI_KEY}', 'X-Request-ID': request_id}
        try:
            async with httpx.AsyncClient(timeout=75, follow_redirects=False, transport=transport) as client:
                response = await client.post(settings.ARK_AI_BASE_URL.rstrip('/') + '/chat', headers=headers,
                    json={'preset': settings.ARK_AI_PRESET, 'messages': [{'role': 'user', 'content': data.text}]})
            result = response.json()
        except (httpx.HTTPError, ValueError):
            # Never retry: the upstream may already have executed/charged.
            return JSONResponse(status_code=502, content={'message': 'Result unavailable; contact the site owner before retrying', 'request_id': request_id})
        if response.status_code != 200:
            return JSONResponse(status_code=response.status_code, content={
                'message': result.get('message', 'AI request failed'), 'request_id': request_id,
                'error': (result.get('data') or {}).get('error'),
            })
        return {'content': result['data']['content'], 'request_id': request_id}

    return app


def app_factory():
    return create_app(Settings())
