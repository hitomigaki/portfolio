"""FastAPIアプリのエントリーポイント。

RoomManager / ConnectionManager は各1個をアプリ全体で共有する
(メモリ管理なので、プロセス内で共有インスタンスを持つのが最も単純)。
テストからは create_app() を呼んで、毎回まっさらな状態のアプリを作れるようにしている。
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.api.rooms import router as rooms_router
from app.core.rate_limiter import RateLimiter
from app.core.room_manager import RoomManager
from app.ws.connection_manager import ConnectionManager
from app.ws.handlers import run_room_ticker, ws_endpoint

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.room_manager = RoomManager()
        app.state.connections = ConnectionManager()
        app.state.room_lookup_rate_limiter = RateLimiter(
            max_attempts=config.ROOM_LOOKUP_RATE_LIMIT_MAX_ATTEMPTS,
            window_sec=config.ROOM_LOOKUP_RATE_LIMIT_WINDOW_SEC,
        )
        ticker_task = asyncio.create_task(
            run_room_ticker(app.state.room_manager, app.state.connections)
        )
        try:
            yield
        finally:
            ticker_task.cancel()
            try:
                await ticker_task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title="コードレース", lifespan=lifespan)
    app.include_router(rooms_router)

    @app.websocket("/ws/{room_code}")
    async def websocket_route(websocket: WebSocket, room_code: str) -> None:
        await ws_endpoint(
            websocket, room_code, websocket.app.state.room_manager, websocket.app.state.connections
        )

    @app.get("/")
    async def index_page() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/room/{room_code}")
    async def room_page(room_code: str) -> FileResponse:
        # room_code自体は使わない(実在チェックはフロントJSがREST経由で行う)。
        # このルートの役目は room.html を返すことだけ。
        return FileResponse(FRONTEND_DIR / "room.html")

    # css/js等の静的ファイルはここでまとめて配信する。
    # 上の個別ルート(/, /room/{code}, /api/*, /ws/*)より後にマウントすることで、
    # 同じパスが来たときは個別ルートが優先されるようにしている。
    if FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="static")

    return app


app = create_app()
