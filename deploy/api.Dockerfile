FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY skillforge ./skillforge

ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -i "${PIP_INDEX_URL}" .

# Compile, inject, and the evaluator resolve this tree from /app, not from
# site-packages. uvicorn's cwd import of /app/skillforge makes parents[2] == /app.
COPY demo/ops-lab ./demo/ops-lab

EXPOSE 8000

CMD ["uvicorn", "skillforge.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
