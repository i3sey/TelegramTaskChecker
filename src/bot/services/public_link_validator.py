"""Async validator for checking public accessibility of submitted links."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

import aiohttp

from src.bot.utils.logging import logger

DEFAULT_TIMEOUT_SECONDS = 5
MAX_REDIRECTS = 5
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

class PublicLinkCheckStatus(StrEnum):
    """High-level public link verification statuses."""

    OK = "OK"
    UNSUPPORTED_SERVICE = "UNSUPPORTED_SERVICE"
    ACCESS_DENIED = "ACCESS_DENIED"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN_TIMEOUT = "UNKNOWN_TIMEOUT"
    UNKNOWN_NETWORK_ERROR = "UNKNOWN_NETWORK_ERROR"
    INVALID_URL = "INVALID_URL"

class SupportedLinkService(StrEnum):
    """Known external services with specialized access checks."""

    FIGMA = "figma"
    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    GOOGLE = "google"
    YANDEX_DISK = "yandex_disk"
    MAIL_RU_CLOUD = "mail_ru_cloud"

@dataclass(slots=True)
class PublicLinkValidationResult:
    """Structured result of public link validation."""

    is_accessible: bool
    service: str | None
    status: PublicLinkCheckStatus
    normalized_url: str
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class ServiceMatcher:
    """Regex-based matcher and metadata for a supported service."""

    service: SupportedLinkService
    display_name: str
    pattern: re.Pattern[str]

SERVICE_MATCHERS: tuple[ServiceMatcher, ...] = (
    ServiceMatcher(
        service=SupportedLinkService.FIGMA,
        display_name="Figma",
        pattern=re.compile(r"^https?://(?:www\.)?figma\.com/(?:file|board|design|proto|slides)/", re.IGNORECASE),
    ),
    ServiceMatcher(
        service=SupportedLinkService.GITHUB,
        display_name="GitHub",
        pattern=re.compile(r"^https?://(?:www\.)?github\.com/[^/]+/[^/?#]+", re.IGNORECASE),
    ),
    ServiceMatcher(
        service=SupportedLinkService.GITLAB,
        display_name="GitLab",
        pattern=re.compile(r"^https?://(?:www\.)?gitlab\.com/[^/]+/[^/?#]+", re.IGNORECASE),
    ),
    ServiceMatcher(
        service=SupportedLinkService.BITBUCKET,
        display_name="Bitbucket",
        pattern=re.compile(r"^https?://(?:www\.)?bitbucket\.org/[^/]+/[^/?#]+", re.IGNORECASE),
    ),
    ServiceMatcher(
        service=SupportedLinkService.GOOGLE,
        display_name="Google Docs / Drive",
        pattern=re.compile(
            r"^https?://(?:(?:docs|drive)\.google\.com)/",
            re.IGNORECASE,
        ),
    ),
    ServiceMatcher(
        service=SupportedLinkService.YANDEX_DISK,
        display_name="Яндекс Диск",
        pattern=re.compile(
            r"^https?://(?:disk\.yandex\.(?:ru|com)|yadi\.sk)/",
            re.IGNORECASE,
        ),
    ),
    ServiceMatcher(
        service=SupportedLinkService.MAIL_RU_CLOUD,
        display_name="Облако Mail.ru",
        pattern=re.compile(
            r"^https?://(?:cloud\.mail\.ru|my\.mail\.ru)/",
            re.IGNORECASE,
        ),
    ),
)

def normalize_url(url: str) -> str:
    """Normalize and validate URL string."""

    normalized = (url or "").strip()
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Invalid URL")

    return normalized

def match_supported_service(url: str) -> ServiceMatcher | None:
    """Match URL against known supported services."""

    for matcher in SERVICE_MATCHERS:
        if matcher.pattern.search(url):
            return matcher
    return None

def build_public_link_error_message(result: PublicLinkValidationResult) -> str:
    """Convert structured validation result into Telegram-friendly message."""

    service_name = result.details.get("display_name") or result.service or "сервис"

    if result.status == PublicLinkCheckStatus.ACCESS_DENIED:
        if result.service == SupportedLinkService.GOOGLE.value:
            return (
                "❌ Документ Google недоступен без авторизации.\n"
                "Откройте доступ по ссылке и отправьте её повторно."
            )
        if result.service in {
            SupportedLinkService.GITHUB.value,
            SupportedLinkService.GITLAB.value,
            SupportedLinkService.BITBUCKET.value,
        }:
            return "❌ Репозиторий недоступен публично."
        if result.service == SupportedLinkService.FIGMA.value:
            return (
                "❌ Файл Figma недоступен без авторизации.\n"
                "Проверьте настройки доступа по ссылке."
            )
        return f"❌ Ссылка на сервис «{service_name}» недоступна без авторизации."

    if result.status == PublicLinkCheckStatus.NOT_FOUND:
        if result.service in {
            SupportedLinkService.GITHUB.value,
            SupportedLinkService.GITLAB.value,
            SupportedLinkService.BITBUCKET.value,
        }:
            return "❌ Репозиторий недоступен публично или не существует."
        return f"❌ Ссылка на сервис «{service_name}» не найдена или больше недоступна."

    if result.status == PublicLinkCheckStatus.UNKNOWN_TIMEOUT:
        return "⚠️ Не удалось проверить ссылку из-за таймаута. Попробуйте позже."

    if result.status == PublicLinkCheckStatus.UNKNOWN_NETWORK_ERROR:
        return "⚠️ Не удалось проверить ссылку из-за сетевой ошибки. Попробуйте позже."

    if result.status == PublicLinkCheckStatus.INVALID_URL:
        return "❌ Некорректная ссылка. Используйте полный URL, например https://example.com"

    return result.message or "❌ Не удалось проверить публичный доступ по ссылке."

async def _fetch_url(
    session: aiohttp.ClientSession,
    url: str,
) -> tuple[int, str, str]:
    """Fetch URL and return status, final URL and response body."""

    async with session.get(url, allow_redirects=True, max_redirects=MAX_REDIRECTS) as response:
        body = await response.text(errors="ignore")
        return response.status, str(response.url), body

def _extract_html_title(html: str) -> str | None:
    """Extract title-like metadata from HTML body."""

    og_title_match = re.search(
        r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if og_title_match:
        return og_title_match.group(1).strip()

    title_match = re.search(r"<title>\s*(.*?)\s*</title>", html, re.IGNORECASE | re.DOTALL)
    if title_match:
        return re.sub(r"\s+", " ", title_match.group(1)).strip()

    return None

def _build_ok_result(
    url: str,
    matcher: ServiceMatcher,
    final_url: str | None = None,
    details: dict[str, Any] | None = None,
) -> PublicLinkValidationResult:
    """Create successful validation result."""

    payload: dict[str, Any] = {"display_name": matcher.display_name}
    if final_url:
        payload["final_url"] = final_url
    if details:
        payload.update(details)

    return PublicLinkValidationResult(
        is_accessible=True,
        service=matcher.service.value,
        status=PublicLinkCheckStatus.OK,
        normalized_url=url,
        details=payload,
    )

def _build_failure_result(
    url: str,
    matcher: ServiceMatcher | None,
    status: PublicLinkCheckStatus,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> PublicLinkValidationResult:
    """Create failed validation result."""

    payload = details.copy() if details else {}
    if matcher:
        payload.setdefault("display_name", matcher.display_name)

    return PublicLinkValidationResult(
        is_accessible=False,
        service=matcher.service.value if matcher else None,
        status=status,
        normalized_url=url,
        message=message,
        details=payload,
    )

async def _check_figma_link(
    session: aiohttp.ClientSession,
    url: str,
    matcher: ServiceMatcher,
) -> PublicLinkValidationResult:
    """Check whether Figma / FigJam link is publicly accessible."""

    status_code, final_url, body = await _fetch_url(session, url)
    page_title = _extract_html_title(body)
    title_markers = {
        "Login to Figma",
        "Figma: The Collaborative Interface Design Tool",
        "You don't have access to this file",
    }

    if status_code == 404:
        return _build_failure_result(
            url=url,
            matcher=matcher,
            status=PublicLinkCheckStatus.NOT_FOUND,
            details={"http_status": status_code, "final_url": final_url, "title": page_title},
        )

    if status_code >= 400:
        return _build_failure_result(
            url=url,
            matcher=matcher,
            status=PublicLinkCheckStatus.ACCESS_DENIED,
            details={"http_status": status_code, "final_url": final_url, "title": page_title},
        )

    if page_title and page_title not in title_markers:
        return _build_ok_result(
            url=url,
            matcher=matcher,
            final_url=final_url,
            details={"http_status": status_code, "title": page_title},
        )

    if any(marker.lower() in body.lower() for marker in title_markers):
        return _build_failure_result(
            url=url,
            matcher=matcher,
            status=PublicLinkCheckStatus.ACCESS_DENIED,
            details={"http_status": status_code, "final_url": final_url, "title": page_title},
        )

    return _build_failure_result(
        url=url,
        matcher=matcher,
        status=PublicLinkCheckStatus.ACCESS_DENIED,
        details={"http_status": status_code, "final_url": final_url, "title": page_title},
    )

async def _check_git_repository_link(
    session: aiohttp.ClientSession,
    url: str,
    matcher: ServiceMatcher,
) -> PublicLinkValidationResult:
    """Check whether repository page is publicly accessible."""

    status_code, final_url, _ = await _fetch_url(session, url)

    if status_code == 404:
        return _build_failure_result(
            url=url,
            matcher=matcher,
            status=PublicLinkCheckStatus.NOT_FOUND,
            details={"http_status": status_code, "final_url": final_url},
        )

    if status_code >= 400:
        return _build_failure_result(
            url=url,
            matcher=matcher,
            status=PublicLinkCheckStatus.ACCESS_DENIED,
            details={"http_status": status_code, "final_url": final_url},
        )

    return _build_ok_result(
        url=url,
        matcher=matcher,
        final_url=final_url,
        details={"http_status": status_code},
    )

async def _check_google_link(
    session: aiohttp.ClientSession,
    url: str,
    matcher: ServiceMatcher,
) -> PublicLinkValidationResult:
    """Check whether Google Docs / Drive file is accessible without login."""

    status_code, final_url, _ = await _fetch_url(session, url)
    final_host = (urlparse(final_url).hostname or "").lower()

    if status_code == 404:
        return _build_failure_result(
            url=url,
            matcher=matcher,
            status=PublicLinkCheckStatus.NOT_FOUND,
            details={"http_status": status_code, "final_url": final_url},
        )

    if final_host == "accounts.google.com":
        return _build_failure_result(
            url=url,
            matcher=matcher,
            status=PublicLinkCheckStatus.ACCESS_DENIED,
            details={"http_status": status_code, "final_url": final_url},
        )

    if status_code >= 400:
        return _build_failure_result(
            url=url,
            matcher=matcher,
            status=PublicLinkCheckStatus.ACCESS_DENIED,
            details={"http_status": status_code, "final_url": final_url},
        )

    return _build_ok_result(
        url=url,
        matcher=matcher,
        final_url=final_url,
        details={"http_status": status_code},
    )

async def _check_cloud_link(
    session: aiohttp.ClientSession,
    url: str,
    matcher: ServiceMatcher,
) -> PublicLinkValidationResult:
    """Check whether cloud sharing link is publicly accessible."""

    status_code, final_url, _ = await _fetch_url(session, url)
    parsed_final_url = urlparse(final_url)
    final_host = (parsed_final_url.hostname or "").lower()
    final_path = parsed_final_url.path.lower()

    if status_code == 404:
        return _build_failure_result(
            url=url,
            matcher=matcher,
            status=PublicLinkCheckStatus.NOT_FOUND,
            details={"http_status": status_code, "final_url": final_url},
        )

    if status_code >= 400:
        return _build_failure_result(
            url=url,
            matcher=matcher,
            status=PublicLinkCheckStatus.ACCESS_DENIED,
            details={"http_status": status_code, "final_url": final_url},
        )

    if matcher.service == SupportedLinkService.YANDEX_DISK:
        if final_host.startswith("disk.yandex.") and final_path in {"", "/"}:
            return _build_failure_result(
                url=url,
                matcher=matcher,
                status=PublicLinkCheckStatus.ACCESS_DENIED,
                details={"http_status": status_code, "final_url": final_url},
            )

    if matcher.service == SupportedLinkService.MAIL_RU_CLOUD:
        if "login" in final_path or "auth" in final_path:
            return _build_failure_result(
                url=url,
                matcher=matcher,
                status=PublicLinkCheckStatus.ACCESS_DENIED,
                details={"http_status": status_code, "final_url": final_url},
            )

    return _build_ok_result(
        url=url,
        matcher=matcher,
        final_url=final_url,
        details={"http_status": status_code},
    )

async def validate_public_link(url: str) -> PublicLinkValidationResult:
    """Validate public accessibility of a submitted URL."""

    try:
        normalized_url = normalize_url(url)
    except ValueError:
        return PublicLinkValidationResult(
            is_accessible=False,
            service=None,
            status=PublicLinkCheckStatus.INVALID_URL,
            normalized_url=(url or "").strip(),
            message="Invalid URL",
            details={},
        )

    matcher = match_supported_service(normalized_url)
    if matcher is None:
        return PublicLinkValidationResult(
            is_accessible=True,
            service=None,
            status=PublicLinkCheckStatus.UNSUPPORTED_SERVICE,
            normalized_url=normalized_url,
            message="Unsupported service, skipping public access verification",
            details={},
        )

    timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT_SECONDS)
    headers = {"User-Agent": BROWSER_USER_AGENT}

    try:
        async with aiohttp.ClientSession(
            timeout=timeout,
            headers=headers,
            cookie_jar=aiohttp.DummyCookieJar(),
            trust_env=False,
        ) as session:
            if matcher.service == SupportedLinkService.FIGMA:
                return await _check_figma_link(session, normalized_url, matcher)

            if matcher.service in {
                SupportedLinkService.GITHUB,
                SupportedLinkService.GITLAB,
                SupportedLinkService.BITBUCKET,
            }:
                return await _check_git_repository_link(session, normalized_url, matcher)

            if matcher.service == SupportedLinkService.GOOGLE:
                return await _check_google_link(session, normalized_url, matcher)

            if matcher.service in {
                SupportedLinkService.YANDEX_DISK,
                SupportedLinkService.MAIL_RU_CLOUD,
            }:
                return await _check_cloud_link(session, normalized_url, matcher)

    except (asyncio.TimeoutError, TimeoutError):
        logger.warning("Public link validation timeout for URL: %s", normalized_url)
        return _build_failure_result(
            url=normalized_url,
            matcher=matcher,
            status=PublicLinkCheckStatus.UNKNOWN_TIMEOUT,
        )
    except aiohttp.ClientError as exc:
        logger.warning("Public link validation network error for URL %s: %s", normalized_url, exc)
        return _build_failure_result(
            url=normalized_url,
            matcher=matcher,
            status=PublicLinkCheckStatus.UNKNOWN_NETWORK_ERROR,
            details={"error": str(exc)},
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.exception("Unexpected public link validation error for URL %s: %s", normalized_url, exc)
        return _build_failure_result(
            url=normalized_url,
            matcher=matcher,
            status=PublicLinkCheckStatus.UNKNOWN_NETWORK_ERROR,
            details={"error": str(exc)},
        )

    return _build_failure_result(
        url=normalized_url,
        matcher=matcher,
        status=PublicLinkCheckStatus.UNKNOWN_NETWORK_ERROR,
    )