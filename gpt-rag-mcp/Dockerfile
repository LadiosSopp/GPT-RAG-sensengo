
FROM python:3.12-slim AS base

# Install curl, certificates, and ODBC Driver 18 for SQL Server
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates gnupg apt-transport-https \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends \
        msodbcsql18 unixodbc-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv via PyPI (wheel provides compiled binary). This is more reliable in slim images.
RUN pip install --no-cache-dir uv \
    && uv --version

WORKDIR /app

# Copy only project metadata first for better layer caching of dependencies.
COPY pyproject.toml README.md ./
# If you already have a lock file committed, copy it too for reproducible builds.
# (Uncomment next line when uv.lock exists)
# COPY uv.lock ./

# Sync (install) dependencies into a managed .venv. --frozen will fail if lock differs.
# Use --no-dev if you have dev dependencies you don't want in the prod image.
RUN uv sync --no-dev

# Now copy the application source code (only files likely to change go later for cache efficiency).
COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Container Apps / general containers expect listening on 0.0.0.0:<port>
EXPOSE 80

ENV PYTHONPATH="/app/src"

# Run the MCP server using uv so it uses the synced environment.
CMD ["uv", "run", "uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "80", "--log-level", "info"]