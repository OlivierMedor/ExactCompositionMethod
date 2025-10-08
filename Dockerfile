# Dockerfile for the final Python + Rust solution

# --- Builder Stage for Rust Compilation ---
FROM python:3.11-slim as rust-builder

# Install Rust and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential pkg-config ca-certificates && \
    rm -rf /var/lib/apt/lists/*
    
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y --profile minimal
ENV PATH="/root/.cargo/bin:${PATH}"

# Install maturin to build the Python wheel from Rust
RUN python -m pip install --no-cache-dir "maturin>=1.5,<2.0"

# Build the Rust core
WORKDIR /app/rustcore
COPY src/rustcore/ ./
RUN maturin build --release -i python3.11

# --- Final Python Stage ---
FROM python:3.11-slim

WORKDIR /app

# Copy the compiled wheel from the builder and install it
COPY --from=rust-builder /app/rustcore/target/wheels/*.whl /tmp/
RUN python -m pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl

# Copy the Python driver script
COPY src/main.py /app/src/main.py

CMD ["python", "-u", "src/main.py"]