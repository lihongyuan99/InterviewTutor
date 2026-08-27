import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse

# 统一日志级别，让 [计时] 等 INFO 日志能够输出到 stderr/日志文件
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from app.api.chat import router as chat_router
from app.api.history import router as history_router
from app.api.interview import router as interview_router
from app.api.notes import router as notes_router
from app.api.task_plan import router as task_plan_router
from app.api.tasks import router as tasks_router
from app.api.settings import router as settings_router
from app.api.knowledge import router as knowledge_router
from app.api.resume import router as resume_router
from app.core.llm_factory import close_http_clients
from app.knowledge.sync import knowledge_sync_service


@asynccontextmanager
async def lifespan(_app: FastAPI):
    knowledge_sync_service.start_background()
    try:
        yield
    finally:
        await knowledge_sync_service.stop_background()
        await close_http_clients()

app = FastAPI(
    title="InterviewTutor API",
    description="Backend API for InterviewTutor",
    version="1.0.0",
    lifespan=lifespan,
)

# 配置 CORS，允许前端跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # 在生产环境中应该限制为特定的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(chat_router, prefix="/api/v1", tags=["Chat"])
app.include_router(history_router, prefix="/api/v1/history", tags=["History"])
app.include_router(notes_router, prefix="/api/v1/notes", tags=["Notes"])
app.include_router(task_plan_router, prefix="/api/v1/agent", tags=["Task Plan"])
app.include_router(tasks_router, prefix="/api/v1", tags=["Tasks"])
app.include_router(settings_router, prefix="/api/v1", tags=["Settings"])
app.include_router(interview_router, prefix="/api/v1/interview", tags=["Interview"])
app.include_router(knowledge_router, prefix="/api/v1/knowledge", tags=["Knowledge"])
app.include_router(resume_router, prefix="/api/v1/resume", tags=["Resume"])


# ===== 前端静态产物伺服（桌面模式 / 单进程部署）=====
# 当存在 web/dist（`npm run build` 产物）时，同源伺服前端页面；
# 未命中的路径回退到 index.html 以支持前端路由（BrowserRouter）。
# 纯后端开发模式（无 dist）行为不变。
_WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


class _SPAStaticFiles(StaticFiles):
    """前端静态资源；未命中的路径回退 index.html（SPA 前端路由）"""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


if _WEB_DIST.is_dir():
    # 注意：mount 必须在所有 API 路由注册之后（FastAPI 按注册顺序匹配）
    app.mount("/", _SPAStaticFiles(directory=_WEB_DIST, html=True), name="web")

    @app.get("/", include_in_schema=False)
    async def root():
        return FileResponse(_WEB_DIST / "index.html")
else:

    @app.get("/")
    async def root():
        return {"message": "Welcome to InterviewTutor API"}
