FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# REPO_ROOT is the parent of the simplifier package, so models.yaml and prompts/ sit beside it.
COPY models.yaml .
COPY prompts prompts
COPY simplifier simplifier

RUN adduser --system --no-create-home app
USER app

EXPOSE 8000

# Exactly one worker: the rate limiter and the cooldowns live in this process's memory, so more
# workers would each keep their own counts and could together go over a model's limit.
CMD ["uvicorn", "simplifier.api.app_api:app", "--host", "0.0.0.0", "--port", "8000"]
