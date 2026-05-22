# TelegramTaskChecker

Telegram bot for managing task submission, review, and campaign workflows.

## Run with Docker Compose

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```
   On Windows:
   ```cmd
   copy .env.example .env
   ```

2. Fill in at least:
   - `BOT_TOKEN`
   - `ADMIN_IDS`
   - `GROQ_API_KEY` if voice transcription is used

3. Start everything:
   ```bash
   docker compose up --build
   ```

This starts:
- `bot`
- `postgres`
- `redis`

Inside Docker Compose, the bot automatically connects to:
- PostgreSQL at `postgres:5432`
- Redis at `redis:6379`

You can configure connections in two ways:
- with `POSTGRES_*` and `REDIS_*` variables
- or with direct `DATABASE_URL` and `REDIS_URL`

Example:

```text
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/telegram_task_checker
REDIS_URL=redis://redis:6379/0
```

## Docker image build on GitHub

The repository includes GitHub Actions workflow:

- file: `.github/workflows/docker.yml`
- trigger: push to `main`
- trigger: git tags like `v1.0.0`
- trigger: manual run via `workflow_dispatch`

The workflow builds and publishes the image to GitHub Container Registry:

```text
ghcr.io/i3sey/telegramtaskchecker
```

Depending on the event, tags will include:
- `latest` for the default branch
- branch name
- git tag
- commit SHA

Example image reference:

```text
ghcr.io/i3sey/telegramtaskchecker:latest
```

## Deploy on a container platform

If your platform can run a long-lived worker/container process, point it to the published image from GHCR and provide environment variables from `.env` or set them directly in the platform dashboard.

Main command inside the image:

```text
python -m src.bot.main
```

This bot uses Telegram long polling, so it does not require an HTTP port to serve requests.