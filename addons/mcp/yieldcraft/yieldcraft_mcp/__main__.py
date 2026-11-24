from pathlib import Path
import argparse, os
from .config import load

def main():
    parser=argparse.ArgumentParser(description='Yieldcraft MCP (analysis only)')
    parser.add_argument('--config',type=Path,default=Path(os.getenv('YIELDCRAFT_MCP_CONFIG','/etc/yieldcraft-mcp/config.toml')))
    args=parser.parse_args(); cfg=load(args.config)
    os.umask(0o077)
    from .server import build_app
    import uvicorn
    uvicorn.run(build_app(cfg),host=cfg.bind,port=cfg.port,workers=1,proxy_headers=False,access_log=False,timeout_keep_alive=5,limit_concurrency=64)
if __name__=='__main__': main()
