import hashlib,json,os,sys
from pathlib import Path
import pytest
from yieldcraft_mcp.config import Config
from yieldcraft_mcp.server import Runtime
from yieldcraft_mcp.auth import SCOPES
TOKEN='test-only-'+('x'*48)
@pytest.fixture
def config(tmp_path):
    root=tmp_path/'finpred'; (root/'bin').mkdir(parents=True); (root/'strategies').mkdir()
    tokens=tmp_path/'tokens.json'; tokens.write_text(json.dumps([{'sha256':hashlib.sha256(TOKEN.encode()).hexdigest(),'project':'default','scopes':sorted(SCOPES)}]));tokens.chmod(0o600)
    return Config(finpred_root=root,state_dir=tmp_path/'state',token_file=tokens,timeout=5,max_artifact_bytes=65536,max_project_bytes=2000000,max_request_bytes=65536)
@pytest.fixture
def runtime(config): return Runtime(config)
@pytest.fixture
def fake(config):
    def write(tool,script):
        p=config.finpred_root/'bin'/tool;p.write_text('#!'+sys.executable+'\n'+script);p.chmod(0o755);return p
    return write
