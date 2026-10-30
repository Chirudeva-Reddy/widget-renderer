# ponytail: one container runs the same dev setup as the README (vite on 5173 proxying to uvicorn on 127.0.0.1:8000),
# so the backend's localhost/5173 origin checks for demo actions keep working unchanged.
FROM node:22-slim
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/python UV_LINK_MODE=copy
WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock backend/
RUN cd backend && uv sync --frozen --no-dev
COPY frontend/package.json frontend/package-lock.json frontend/
RUN cd frontend && npm ci

COPY backend backend
COPY frontend frontend
RUN rm -f backend/restaurant.sqlite

EXPOSE 5173
CMD ["sh", "-c", "cd backend && uv run --frozen uvicorn app.main:app --host 127.0.0.1 --port 8000 & cd frontend && exec npx vite --host 0.0.0.0 --port 5173 --strictPort"]
