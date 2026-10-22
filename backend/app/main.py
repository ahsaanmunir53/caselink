"""FastAPI application: settings, storage, models, the LangGraph workflows and the routes."""

import logging
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.graphs import Deps, build_ingest_graph, build_review_graph
from app.ai.llm import build_model_chains, check_models, model_label
from app.api import cases, misc
from app.api.common import RateLimiter
from app.auth import bootstrap_users
from app.config import Settings, get_settings
from app.core.aio import postgres_loop_problem
from app.db.session import init_db, make_engine, make_sessionmaker
from app.seed import seed_if_empty

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("caselink")


async def _postgres_checkpointer(settings: Settings, stack: AsyncExitStack):
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(conninfo=settings.database_url, min_size=1, max_size=4, open=False,
                               kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                               check=AsyncConnectionPool.check_connection)
    await pool.open()
    stack.push_async_callback(pool.close)
    saver = AsyncPostgresSaver(pool)
    await saver.setup()
    return saver


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings)
        await init_db(engine)
        sessionmaker = make_sessionmaker(engine)
        async with AsyncExitStack() as stack:
            if settings.uses_postgres:
                problem = postgres_loop_problem()
                if problem:
                    raise RuntimeError(problem)
                checkpointer = await _postgres_checkpointer(settings, stack)
            else:
                checkpointer = InMemorySaver()
            try:
                changes = await check_models(settings)
            except Exception as exc:
                log.warning("Model check skipped: %s", type(exc).__name__)
                changes = []
            models, agent_models = build_model_chains(settings)
            deps = Deps(settings=settings, sessionmaker=sessionmaker, models=models, agent_models=agent_models,
                        checkpointer=checkpointer)
            deps.review_graph = build_review_graph(deps, checkpointer)
            deps.ingest_graph = build_ingest_graph(deps, checkpointer)
            app.state.settings, app.state.deps = settings, deps
            app.state.limiter = RateLimiter(settings.rate_limit_per_minute)
            app.state.model_label = model_label(settings)
            app.state.model_changes = changes
            created = await bootstrap_users(sessionmaker, settings)
            if created:
                log.info("Created accounts: %s", ", ".join(created))
            seeded = await seed_if_empty(deps)
            log.info("CaseLink ready: model=%s storage=%s demo=%s seeded=%d", app.state.model_label,
                     "postgres" if settings.uses_postgres else "local", settings.demo_mode, seeded)
            yield
        await engine.dispose()

    app = FastAPI(title="CaseLink API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_credentials=False,
                       allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type", "X-Cron-Secret"])
    app.include_router(misc.router)
    app.include_router(cases.router)
    return app


app = create_app()
