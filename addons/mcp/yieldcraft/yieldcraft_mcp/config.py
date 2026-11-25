from __future__ import annotations
import re, tomllib
from ipaddress import IPv6Address
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from urllib.parse import urlsplit

DNS = re.compile(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z')
DNS_LABEL = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?')
AUTHORITY = re.compile(r'([A-Za-z0-9.-]{1,253}|\[[A-Fa-f0-9:.]+\])(?::([0-9]{1,5}))?')
HTTPS_URL = re.compile(r"https://[A-Za-z0-9:/._~!$&'()*+,;=@%\[\]-]+")

def authority(value):
    m = AUTHORITY.fullmatch(value)
    if not m: raise ValueError('invalid HTTP authority')
    host, port = m.groups()
    host = host.lower()
    if host.startswith('['):
        host = f'[{IPv6Address(host[1:-1]).compressed}]'
    elif not all(DNS_LABEL.fullmatch(label) for label in host.split('.')):
        raise ValueError('invalid HTTP host')
    port = int(port) if port is not None else None
    if port is not None and not 1 <= port <= 65535: raise ValueError('invalid HTTP port')
    return host, port

def https_url(value):
    if not HTTPS_URL.fullmatch(value) or re.search(r'%(?![0-9A-Fa-f]{2})', value):
        raise ValueError('HTTPS URLs without credentials/query/fragment required')
    parsed = urlsplit(value)
    authority(parsed.netloc)
    return parsed

def https_origin(value):
    host, port = authority(https_url(value).netloc)
    return f'https://{host}' + (f':{port}' if port not in (None, 443) else '')

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
        for u in [self.public_url,self.oauth_issuer,self.oauth_introspection_url]:
            if u is not None: https_url(u)
        if self.public_url and https_url(self.public_url).path!='/mcp': raise ValueError('public_url must end in /mcp')
        if any(https_url(u).path for u in self.allowed_origins): raise ValueError('allowed_origins must be HTTPS origins without paths')
        oauth=(self.oauth_issuer,self.oauth_introspection_url,self.oauth_client_id,self.oauth_secret_file)
        if any(v is not None for v in oauth) and not all((*oauth,self.public_url)): raise ValueError('complete OAuth introspection configuration required')
        if self.oauth_client_id is not None and not re.fullmatch(r'[!-9;-~]{1,1024}',self.oauth_client_id):
            raise ValueError('invalid OAuth client ID')
        return self

def load(path: Path) -> Config:
    with path.open('rb') as f: return Config.model_validate(tomllib.load(f))
