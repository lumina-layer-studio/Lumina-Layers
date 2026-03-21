"""Lumina Studio API — Server Entry Point.
Lumina Studio API — 服务启动入口。

Minimal entry script that imports the FastAPI application instance
and starts the uvicorn ASGI server. Run with ``python api_server.py``.
最小化入口脚本，导入 FastAPI 应用实例并启动 uvicorn ASGI 服务器。
通过 ``python api_server.py`` 运行。
"""

import uvicorn

if __name__ == "__main__":
    from api.app import app

    uvicorn.run(app, host="0.0.0.0", port=8000)
