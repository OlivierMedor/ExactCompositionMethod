# Dockerfile (multi-stage)
FROM ghcr.io/pyo3/maturin:v1.7.1 AS rust-build
WORKDIR /io
COPY src/rustcore/ /io/
RUN maturin build --release -i python3.11 --compatibility manylinux2014 --out /dist

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 USE_RUST_CORE=1 PYTHONPATH=/app
WORKDIR /app
COPY src/ /app/src/
RUN python -m pip install --no-cache-dir fastapi uvicorn "pydantic>=2,<3"
COPY --from=rust-build /dist/*.whl /tmp/
RUN python -m pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl
EXPOSE 8000
CMD ["python", "-m", "src.app"]
