from __future__ import annotations
import os, re, tomllib
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from urllib.parse import urlsplit

DNS = re.compile(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z')
class Config(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    finpred_root: Path
    state_dir: Path
    token_file: Path
    bind: str = '127.0.0.1'
    port: int = Field(8788, ge=1, le=65535)
    public_url: str | None = None
    allowed_origins: list[str] = []
    allowed_hosts: list[str] = []
    offer_hosts: list[str] = []
    allow_llm: bool = False
    enable_live: bool = False
    daemon_config: Path | None = None
    daemon_autostart: bool = False
    timeout: int = Field(120, ge=5, le=900)
    max_concurrent: int = Field(4, ge=1, le=16)
    max_artifact_bytes: int = Field(2_000_000, ge=65536, le=26_000_000)
    max_project_bytes: int = Field(100_000_000, ge=2_000_000, le=2_000_000_000)
    max_request_bytes: int = Field(8_000_000, ge=65536, le=32_000_000)
    oauth_issuer: str | None = None
    oauth_introspection_url: str | None = None
    oauth_client_id: str | None = None
    oauth_secret_file: Path | None = None
    @field_validator('finpred_root','state_dir','token_file','daemon_config','oauth_secret_file')
    @classmethod
    def absolute(cls, v):
        if v is not None and not v.is_absolute(): raise ValueError('absolute paths required')
        return v
    @field_validator('allowed_hosts','offer_hosts')
    @classmethod
    def hosts(cls, v):
        if len(v)>64 or any(not DNS.fullmatch(x) for x in v): raise ValueError('exact lowercase DNS names required')
        return sorted(set(v))
    @model_validator(mode='after')
    def validate_config(self):
        if self.bind not in ('127.0.0.1','::1'): raise ValueError('bind only to loopback; use TLS proxy')
        if not set(self.offer_hosts)<=set(self.allowed_hosts): raise ValueError('offer_hosts must be a subset of allowed_hosts')
        if self.daemon_autostart and not self.daemon_config: raise ValueError('daemon config required')
        for u in [self.public_url,self.oauth_issuer,self.oauth_introspection_url,*self.allowed_origins]:
            if u:
                p=urlsplit(u)
                if p.scheme!='https' or not p.hostname or p.username or p.password or p.query or p.fragment: raise ValueError('HTTPS URLs without credentials/query/fragment required')
        if self.public_url and urlsplit(self.public_url).path!='/mcp': raise ValueError('public_url must end in /mcp')
        if any((self.oauth_issuer,self.oauth_introspection_url,self.oauth_client_id,self.oauth_secret_file)) and not all((self.oauth_issuer,self.oauth_introspection_url,self.oauth_client_id,self.oauth_secret_file,self.public_url)): raise ValueError('complete OAuth introspection configuration required')
        return self

def load(path: Path) -> Config:
    with path.open('rb') as f: return Config.model_validate(tomllib.load(f))
