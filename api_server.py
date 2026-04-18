"""Lumina Studio API — Server Entry Point.
Lumina Studio API — 服务启动入口。

Minimal entry script that imports the FastAPI application instance
and starts the uvicorn ASGI server. Run with ``python api_server.py``.
最小化入口脚本，导入 FastAPI 应用实例并启动 uvicorn ASGI 服务器。
通过 ``python api_server.py`` 运行。
"""

import os
import uvicorn

if __name__ == "__main__":
    from api.app import app

    _api_host = os.environ.get("LUMINA_HOST", "0.0.0.0").strip() or "0.0.0.0"
    uvicorn.run(app, host=_api_host, port=8000)
