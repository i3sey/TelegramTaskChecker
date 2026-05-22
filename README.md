# TelegramTaskChecker

Telegram bot for managing task submission, review, and campaign workflows.

## Single-container Docker deployment

The project is packaged into a **single Docker container**.

Inside one container it starts:

- the Telegram bot
- PostgreSQL
- Redis

This means the container can be deployed on a platform by simply pointing it to the built image from GitHub Container Registry and setting environment variables.

## Required environment variables

At minimum, set:

- `BOT_TOKEN`
- `ADMIN_IDS`

Optional if used by your bot features:

- `GROQ_API_KEY`
- `HTTP_PROXY`
- `HTTPS_PROXY`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`
- `POSTGRES_PORT`
- `REDIS_PORT`
- `REDIS_PASSWORD`

Default internal values if not overridden:

```text
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=telegram_task_checker
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0
```

The container automatically builds:

- `DATABASE_URL`
- `REDIS_URL`

So for the single-container deployment you usually do **not** need to provide external database or Redis connection strings.

## Run locally with Docker

Build image:

```bash
docker build -t telegramtaskchecker .
```

Run container:

```bash
docker run -d \
  --name telegramtaskchecker \
  -e BOT_TOKEN=your_bot_token \
  -e ADMIN_IDS=123456789 \
  -e GROQ_API_KEY=your_groq_api_key \
  -v telegramtaskchecker_pgdata:/var/lib/postgresql/data \
  ghcr.io/i3sey/telegramtaskchecker:latest
```

On Windows CMD:

```cmd
docker build -t telegramtaskchecker .
docker run -d ^
  --name telegramtaskchecker ^
  -e BOT_TOKEN=your_bot_token ^
  -e ADMIN_IDS=123456789 ^
  -e GROQ_API_KEY=your_groq_api_key ^
  -v telegramtaskchecker_pgdata:/var/lib/postgresql/data ^
  ghcr.io/i3sey/telegramtaskchecker:latest
```

The named volume is important because PostgreSQL data is stored inside the same container image layout and should persist across restarts.

## GitHub Actions: automatic image build

The repository includes GitHub Actions workflow:

- file: `.github/workflows/docker.yml`
- trigger: push to `main`
- trigger: git tags like `v1.0.0`
- trigger: manual run via `workflow_dispatch`

The workflow builds and publishes the Docker image to GitHub Container Registry:

```text
ghcr.io/i3sey/telegramtaskchecker
```

Depending on the event, tags include:

- `latest` for the default branch
- branch name
- git tag
- commit SHA

Example image reference:

```text
ghcr.io/i3sey/telegramtaskchecker:latest
```

## Deploy on a container platform

If your platform supports running a long-lived container/worker process, you can use:

```text
ghcr.io/i3sey/telegramtaskchecker:latest
```

Set the required environment variables in the platform dashboard:

- `BOT_TOKEN`
- `ADMIN_IDS`

Optionally also set:

- `GROQ_API_KEY`

No separate PostgreSQL or Redis service is required for this deployment mode, because both are started inside the same container automatically.

## Docker Compose

`docker-compose.yml` may still be used for local multi-service development if needed, but the main deployment target is now the **single published container image**.

## Runtime behavior

The container entrypoint automatically:

1. initializes PostgreSQL data if needed
2. starts PostgreSQL
3. creates the application database if it does not exist
4. starts Redis
5. starts the Telegram bot

This bot uses Telegram long polling, so it does not require an HTTP port to serve requests.