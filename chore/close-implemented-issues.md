# Закрыть реализованные задачи

В этом PR собраны мелкие изменения и фиксы, которые уже реализованы в кодовой базе и закрывают соответствующие issue.

Короткое описание изменений:

- Реализована Redis-очередь с блокировками и TTL для рецензий (QueueService).
  - Файл: `src/bot/services/queue_service.py`
  - Соответствует: Issue #14 (MVP 2.1)

- Реализован интерфейс и рабочий поток для экспертов: выдача работы, блокировка, ввод оценки, комментарий, сохранение рецензии, отправка в Google Sheets.
  - Файл: `src/bot/handlers/expert_router.py`
  - Соответствует: Issue #21 (MVP 1.2)

- Реализована система нотификаций с throttling/queue и безопасной HTML-экранизацией.
  - Файл: `src/bot/services/notification_service.py`
  - Соответствует: Issue #28 (MVP 1.4) и Issue #22 (Reliability.2) - Telegram throttling

- Небольшие правки и фиксы, связанные с регистрацией и приглашениями, а также с рендерингом HTML в уведомлениях.
  - Файлы: `src/bot/handlers/auth_router.py`, `src/bot/services/notification_service.py`

Пожалуйста, создайте PR из ветки `chore/close-issues-14-21-22-28` в `main` и добавьте описание/комментарии по необходимости.

Closes #14
Closes #21
Closes #22
Closes #28
