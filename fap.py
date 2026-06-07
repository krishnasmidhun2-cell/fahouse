from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)
DEFAULT_ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,image/apng,*/*;q=0.8"
)
DEFAULT_ACCEPT_LANGUAGE = "en-US,en;q=0.9"
PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")
FAP_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = FAP_DIR / "config.local.json"
TEMPLATE_PATHS = {
    "document": FAP_DIR / "header-for-doc.txt",
    "signed_view": FAP_DIR / "header-for-signed-view.txt",
}


class ProtectedEndpointError(RuntimeError):
    pass


class VideoConfigError(RuntimeError):
    pass


@dataclass
class ClientConfig:
    base_url: str = "https://faphouse.com"
    cookie: str = ""
    user_agent: str = DEFAULT_USER_AGENT
    accept_language: str = DEFAULT_ACCEPT_LANGUAGE
    timeout: int = 20
    default_headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, config_path: str | os.PathLike[str] | None = None) -> "ClientConfig":
        path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        raw: dict[str, Any] = {}
        if path.exists():
            raw = load_config_mapping(path)

        default_headers = raw.get("default_headers") or {}
        config = cls(
            base_url=os.getenv("FAP_BASE_URL", raw.get("base_url", cls.base_url)),
            cookie=os.getenv("FAP_COOKIE", raw.get("cookie", "")),
            user_agent=os.getenv("FAP_USER_AGENT", raw.get("user_agent", DEFAULT_USER_AGENT)),
            accept_language=os.getenv(
                "FAP_ACCEPT_LANGUAGE",
                raw.get("accept_language", DEFAULT_ACCEPT_LANGUAGE),
            ),
            timeout=int(os.getenv("FAP_TIMEOUT", raw.get("timeout", 20))),
            default_headers={
                str(key): str(value)
                for key, value in default_headers.items()
                if value not in (None, "")
            },
        )
        return config


def load_config_mapping(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return {}

    try:
        data = json.loads(content)
    except json.JSONDecodeError as json_error:
        try:
            data = ast.literal_eval(content)
        except (SyntaxError, ValueError) as literal_error:
            raise ValueError(
                "Invalid config format in "
                f"{path}. Use JSON, or a Python-style dict/string literal for local files. "
                f"JSON error: {json_error.msg} at line {json_error.lineno}, column {json_error.colno}."
            ) from literal_error

    if not isinstance(data, dict):
        raise ValueError(f"Invalid config format in {path}: top-level value must be an object.")

    return data


def load_selenium_cookie_file(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("cookies")
    if not isinstance(data, list):
        raise ValueError(
            f"Invalid Selenium cookie file {path}: expected a JSON list "
            "or an object containing a 'cookies' list."
        )

    return [item for item in data if isinstance(item, dict)]


def sanitize_filename(value: str, fallback: str = "video") -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", value).strip(" ._")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:180] or fallback


def default_video_output_path(
    config_result: dict[str, Any],
    selected_source: dict[str, str],
) -> Path:
    video_id = str(config_result.get("video_id") or "video")
    title = str(config_result.get("title") or f"video-{video_id}")
    title = re.sub(r"\s*[|\-–—]\s*FapHouse\s*$", "", title, flags=re.IGNORECASE)
    format_name = sanitize_filename(selected_source.get("format") or "best", "best")
    filename = sanitize_filename(
        f"{sanitize_filename(title, f'video-{video_id}')} [{format_name}]",
        f"video-{video_id}",
    )[:220]

    extension = ".mp4"
    if selected_source.get("source_type") == "direct":
        suffix = Path(urlparse(selected_source["url"]).path).suffix
        if suffix and 1 < len(suffix) <= 8:
            extension = suffix
    return Path.cwd() / f"{filename}{extension}"


@dataclass
class HeaderTemplate:
    name: str
    file_path: Path
    request_url: str | None
    payload: str | None
    headers: dict[str, str]

    def render_request_url(self, context: dict[str, Any]) -> str | None:
        if not self.request_url:
            return None
        rendered = render_placeholders(self.request_url, context).strip()
        return rendered or None

    def render_payload(self, context: dict[str, Any]) -> str | None:
        if not self.payload:
            return None
        rendered = render_placeholders(self.payload, context).strip()
        return rendered or None

    def render_headers(self, context: dict[str, Any]) -> dict[str, str]:
        rendered: dict[str, str] = {}
        for key, value in self.headers.items():
            rendered_key = render_placeholders(key, context).strip()
            rendered_value = render_placeholders(value, context).strip()
            if not rendered_key or not rendered_value:
                continue
            rendered[rendered_key] = rendered_value

        authority = rendered.pop(":authority", "")
        rendered.pop(":method", None)
        rendered.pop(":scheme", None)
        rendered.pop(":path", None)
        rendered.pop("content-length", None)

        normalized: dict[str, str] = {}
        if authority:
            normalized["Host"] = authority

        for key, value in rendered.items():
            if value.lower() == "null":
                continue
            normalized[canonicalize_header_name(key)] = value

        return normalized


def render_placeholders(template_value: str, context: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = context.get(key, "")
        return "" if value is None else str(value)

    return PLACEHOLDER_RE.sub(replace, template_value)


def canonicalize_header_name(name: str) -> str:
    special = {
        "dnt": "DNT",
        "etag": "ETag",
        "te": "TE",
        "user-agent": "User-Agent",
        "referer": "Referer",
        "x-csrf-token": "X-CSRF-Token",
        "x-requested-with": "X-Requested-With",
        "x-signed-with": "X-Signed-With",
    }
    lowered = name.lower()
    if lowered in special:
        return special[lowered]
    return "-".join(part.capitalize() for part in lowered.split("-"))


def parse_header_template(template_name: str, file_path: Path) -> HeaderTemplate:
    lines = file_path.read_text(encoding="utf-8").splitlines()

    request_url = None
    payload_lines: list[str] = []
    headers: dict[str, str] = {}
    mode: str | None = None
    pending_key: str | None = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line and mode != "headers":
            continue

        lower = line.lower()
        if lower.startswith("requesturl:") or lower.startswith("request url:"):
            request_url = line.split(":", 1)[1].strip()
            continue
        if lower == "payload:":
            mode = "payload"
            continue
        if lower in {"header", "request header:"}:
            mode = "headers"
            continue

        if mode == "payload":
            if line:
                payload_lines.append(raw_line)
            continue

        if mode == "headers" and line:
            if pending_key is None:
                pending_key = raw_line.strip()
            else:
                headers[pending_key] = raw_line.strip()
                pending_key = None

    payload = "\n".join(payload_lines).strip() or None
    return HeaderTemplate(
        name=template_name,
        file_path=file_path,
        request_url=request_url,
        payload=payload,
        headers=headers,
    )


class FapClient:
    def __init__(self, config: ClientConfig, template_paths: dict[str, Path] | None = None):
        self.config = config
        self.template_paths = template_paths or TEMPLATE_PATHS
        self._templates: dict[str, HeaderTemplate] = {}
        self.session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.import_cookie_header(self.config.cookie)

    def import_cookie_header(self, cookie_header: str) -> None:
        """Copy a standard Cookie header into this client's requests session."""
        if not cookie_header.strip():
            return

        parsed = SimpleCookie()
        parsed.load(cookie_header)
        for morsel in parsed.values():
            self.session.cookies.set(morsel.key, morsel.value)

    def import_selenium_cookies(self, cookies: list[dict[str, Any]]) -> None:
        """Import the result of Selenium's driver.get_cookies()."""
        for cookie in cookies:
            name = str(cookie.get("name") or "").strip()
            if not name:
                continue

            value = str(cookie.get("value") or "")
            kwargs: dict[str, Any] = {}
            if cookie.get("domain"):
                kwargs["domain"] = str(cookie["domain"])
            if cookie.get("path"):
                kwargs["path"] = str(cookie["path"])
            if cookie.get("secure") is not None:
                kwargs["secure"] = bool(cookie["secure"])
            if cookie.get("expiry") is not None:
                try:
                    kwargs["expires"] = int(cookie["expiry"])
                except (TypeError, ValueError):
                    pass

            self.session.cookies.set(name, value, **kwargs)

    def get_template(self, template_name: str) -> HeaderTemplate:
        if template_name not in self._templates:
            file_path = self.template_paths[template_name]
            if file_path.exists():
                self._templates[template_name] = parse_header_template(
                    template_name,
                    file_path,
                )
            else:
                self._templates[template_name] = HeaderTemplate(
                    name=template_name,
                    file_path=file_path,
                    request_url=None,
                    payload=None,
                    headers={},
                )
        return self._templates[template_name]

    def resolve_url(self, value: str | None) -> str:
        if not value:
            return self.config.base_url.rstrip("/")
        if value.startswith("http://") or value.startswith("https://"):
            return value
        return urljoin(self.config.base_url.rstrip("/") + "/", value.lstrip("/"))

    def build_context(
        self,
        page_url: str | None = None,
        path: str | None = None,
        referer: str | None = None,
        **extra_context: Any,
    ) -> dict[str, Any]:
        resolved_page_url = self.resolve_url(page_url) if page_url else None
        resolved_path = path
        if not resolved_path and resolved_page_url:
            parsed = urlparse(resolved_page_url)
            resolved_path = parsed.path or "/"
            if parsed.query:
                resolved_path = f"{resolved_path}?{parsed.query}"

        context = {
            "base_url": self.config.base_url.rstrip("/"),
            "page_url": resolved_page_url or "",
            "path": resolved_path or "",
            "referer": referer or resolved_page_url or "",
            "cookie": self.config.cookie,
            "user_agent": self.config.user_agent,
            "accept_language": self.config.accept_language,
            "host": urlparse(self.config.base_url).netloc,
        }
        context.update(extra_context)
        return context

    def build_headers(
        self,
        template_name: str,
        page_url: str | None = None,
        path: str | None = None,
        referer: str | None = None,
        extra_headers: dict[str, str] | None = None,
        **extra_context: Any,
    ) -> dict[str, str]:
        template = self.get_template(template_name)
        context = self.build_context(
            page_url=page_url,
            path=path,
            referer=referer,
            **extra_context,
        )
        headers = template.render_headers(context)
        headers.setdefault("User-Agent", self.config.user_agent)
        headers.setdefault("Accept-Language", self.config.accept_language)
        headers.setdefault("Accept", DEFAULT_ACCEPT)

        if self.config.cookie and "Cookie" not in headers:
            headers["Cookie"] = self.config.cookie

        for key, value in self.config.default_headers.items():
            if value not in (None, ""):
                headers[canonicalize_header_name(key)] = str(value)

        for key, value in (extra_headers or {}).items():
            if value not in (None, ""):
                headers[canonicalize_header_name(key)] = str(value)

        request_url = self.resolve_url(page_url) if page_url else self.config.base_url
        session_cookie = self.session_cookie_header(request_url)
        if session_cookie:
            headers["Cookie"] = session_cookie

        if not headers.get("Cookie"):
            headers.pop("Cookie", None)

        return headers

    def preview_template(
        self,
        template_name: str,
        page_url: str | None = None,
        path: str | None = None,
        referer: str | None = None,
        **extra_context: Any,
    ) -> dict[str, Any]:
        template = self.get_template(template_name)
        context = self.build_context(
            page_url=page_url,
            path=path,
            referer=referer,
            **extra_context,
        )
        request_url = template.render_request_url(context) or page_url
        return {
            "template": template_name,
            "request_url": request_url,
            "payload": template.render_payload(context),
            "headers": self.build_headers(
                template_name,
                page_url=page_url,
                path=path,
                referer=referer,
                **extra_context,
            ),
        }

    def assert_public_html_url(self, url: str) -> None:
        path = urlparse(url).path or "/"
        if path.startswith("/api/"):
            raise ProtectedEndpointError(
                f"Blocked protected/private endpoint request for path: {path}"
            )

    def fetch_html(self, page_url: str) -> str:
        url = self.resolve_url(page_url)
        self.assert_public_html_url(url)
        headers = self.build_headers("document", page_url=url)
        response = self.session.get(url, headers=headers, timeout=self.config.timeout)
        response.raise_for_status()
        return response.text

    def fetch_soup(self, page_url: str) -> BeautifulSoup:
        return BeautifulSoup(self.fetch_html(page_url), "html.parser")

    def extract_view_state(self, html: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "html.parser")
        script_tag = soup.find("script", id="view-state-data")
        if not script_tag or not script_tag.string:
            return {}
        try:
            return json.loads(script_tag.string)
        except json.JSONDecodeError:
            return {}

    def inspect_video(self, page_url: str) -> dict[str, Any]:
        resolved_url = self.resolve_url(page_url)
        html = self.fetch_html(resolved_url)
        soup = BeautifulSoup(html, "html.parser")
        view_state = self.extract_view_state(html)
        parsed_url = urlparse(resolved_url)

        user = view_state.get("user") if isinstance(view_state.get("user"), dict) else {}
        video = view_state.get("video") if isinstance(view_state.get("video"), dict) else {}

        return {
            "url": resolved_url,
            "title": soup.title.get_text(strip=True) if soup.title else None,
            "has_view_state": bool(view_state),
            "view_state_keys": sorted(view_state.keys()),
            "video_id": video.get("videoId") or video.get("id"),
            "video_slug": parsed_url.path.rstrip("/").split("/")[-1] or None,
            "video_access_type": video.get("videoAccessType"),
            "video_view_allowed": video.get("videoViewAllowed"),
            "studio_name": video.get("studioName"),
            "studio_url": self.resolve_url(video["studioUrl"]) if video.get("studioUrl") else None,
            "user_email_present": bool(user.get("email")),
            "view_state": view_state,
        }

    def fetch_original_video_config(
        self,
        page_url: str,
        video_id: str | int | None = None,
    ) -> dict[str, Any]:
        """
        Fetch the authenticated original-video-config endpoint for one video.

        This is intentionally the only API endpoint exposed by this client. The
        normal HTML fetch path continues to reject arbitrary /api/ URLs.
        """
        resolved_page_url = self.resolve_url(page_url)
        inspection = self.inspect_video(resolved_page_url)
        resolved_video_id = video_id or inspection.get("video_id")
        if resolved_video_id in (None, ""):
            raise VideoConfigError(
                "Could not find video_id in the page view-state. "
                "Pass it explicitly with --video-id."
            )

        safe_video_id = quote(str(resolved_video_id), safe="")
        endpoint = self.resolve_url(
            f"/api/videos/{safe_video_id}/original-video-config"
        )
        headers = self.build_authenticated_api_headers(resolved_page_url)
        response = self.session.get(
            endpoint,
            headers=headers,
            timeout=self.config.timeout,
        )

        if response.status_code in {401, 403}:
            raise VideoConfigError(
                f"Video config request returned HTTP {response.status_code}. "
                "The login cookies may be missing, expired, or not authorized "
                "for this video."
            )

        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise VideoConfigError(
                "Video config endpoint did not return valid JSON."
            ) from exc

        if not isinstance(payload, dict):
            raise VideoConfigError("Video config response must be a JSON object.")

        stream_formats = payload.get("streamFormats") or {}
        download_formats = payload.get("downloadFormats") or {}
        if not isinstance(stream_formats, dict):
            stream_formats = {}
        if not isinstance(download_formats, dict):
            download_formats = {}

        return {
            "page_url": resolved_page_url,
            "video_id": str(resolved_video_id),
            "title": inspection.get("title"),
            "endpoint": endpoint,
            "stream_formats": stream_formats,
            "download_formats": download_formats,
            "raw_config": payload,
        }

    def build_authenticated_api_headers(self, page_url: str) -> dict[str, str]:
        template_name = "signed_view"
        template_path = self.template_paths.get(template_name)
        if not template_path or not template_path.exists():
            template_name = "document"

        fallback_path = self.template_paths.get(template_name)
        if not fallback_path or not fallback_path.exists():
            headers = {
                "User-Agent": self.config.user_agent,
                "Accept-Language": self.config.accept_language,
                "Accept": "application/json, text/plain, */*",
                "Referer": page_url,
                "X-Requested-With": "XMLHttpRequest",
            }
            session_cookie = self.session_cookie_header(page_url)
            if session_cookie:
                headers["Cookie"] = session_cookie
            headers.update(self.config.default_headers)
            return headers

        headers = self.build_headers(
            template_name,
            page_url=page_url,
            referer=page_url,
            extra_headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": page_url,
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        return headers

    def resolve_format_source(
        self,
        config_result: dict[str, Any],
        requested_format: str | None,
        source_type: str,
    ) -> dict[str, str]:
        stream_formats = config_result.get("stream_formats") or {}
        download_formats = config_result.get("download_formats") or {}

        if source_type == "stream":
            selected = self.select_format(stream_formats, requested_format)
            if not selected:
                raise VideoConfigError("No matching M3U8 stream format was found.")
            return {
                "source_type": "stream",
                "format": selected[0],
                "url": selected[1],
            }

        if source_type == "direct":
            selected = self.select_format(download_formats, requested_format)
            if not selected:
                raise VideoConfigError("No matching direct-download format was found.")
            return {
                "source_type": "direct",
                "format": selected[0],
                "url": selected[1],
            }

        try:
            direct = self.select_format(download_formats, requested_format)
        except VideoConfigError:
            direct = None
        if direct:
            return {
                "source_type": "direct",
                "format": direct[0],
                "url": direct[1],
            }

        try:
            stream = self.select_format(stream_formats, requested_format)
        except VideoConfigError:
            stream = None
        if stream:
            return {
                "source_type": "stream",
                "format": stream[0],
                "url": stream[1],
            }

        raise VideoConfigError("No usable stream or direct-download URL was found.")

    def select_format(
        self,
        formats: dict[str, Any],
        requested_format: str | None,
    ) -> tuple[str, str] | None:
        usable: dict[str, str] = {}
        for key, raw_value in formats.items():
            url = self.extract_source_url(raw_value)
            if url:
                usable[str(key)] = url

        if not usable:
            return None

        if requested_format:
            if requested_format in usable:
                return requested_format, usable[requested_format]

            lowered = requested_format.lower()
            for key, url in usable.items():
                if key.lower() == lowered:
                    return key, url

            available = ", ".join(sorted(usable, key=self.format_sort_key))
            raise VideoConfigError(
                f"Format {requested_format!r} was not found. Available: {available}"
            )

        best_key = max(usable, key=self.format_sort_key)
        return best_key, usable[best_key]

    def extract_source_url(self, value: Any) -> str | None:
        if isinstance(value, str):
            candidate = value.strip()
            return self.resolve_media_url(candidate) if candidate else None
        if isinstance(value, dict):
            for key in ("url", "src", "link", "file"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return self.resolve_media_url(candidate.strip())
        return None

    def resolve_media_url(self, value: str) -> str:
        if value.startswith("http://") or value.startswith("https://"):
            return value
        if value.startswith("//"):
            scheme = urlparse(self.config.base_url).scheme or "https"
            return f"{scheme}:{value}"
        return urljoin(self.config.base_url.rstrip("/") + "/", value)

    def format_sort_key(self, format_name: str) -> tuple[int, str]:
        matches = re.findall(r"\d+", format_name)
        numeric = max((int(value) for value in matches), default=-1)
        return numeric, format_name.lower()

    def download_video_source(
        self,
        source: dict[str, str],
        page_url: str,
        output_path: Path,
        overwrite: bool = False,
    ) -> Path:
        output_path = output_path.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists() and not overwrite:
            raise FileExistsError(
                f"Output already exists: {output_path}. Use --overwrite to replace it."
            )

        if source["source_type"] == "stream":
            self.download_hls(
                source_url=source["url"],
                page_url=page_url,
                output_path=output_path,
                overwrite=overwrite,
            )
        else:
            self.download_direct_file(
                source_url=source["url"],
                page_url=page_url,
                output_path=output_path,
            )
        return output_path

    def download_direct_file(
        self,
        source_url: str,
        page_url: str,
        output_path: Path,
    ) -> None:
        headers = self.build_download_headers(page_url)
        temporary_path = output_path.with_name(f"{output_path.name}.part")
        temporary_path.unlink(missing_ok=True)
        try:
            with self.session.get(
                source_url,
                headers=headers,
                timeout=(self.config.timeout, 120),
                stream=True,
            ) as response:
                response.raise_for_status()
                with temporary_path.open("wb") as output_file:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            output_file.write(chunk)
            os.replace(temporary_path, output_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

    def download_hls(
        self,
        source_url: str,
        page_url: str,
        output_path: Path,
        overwrite: bool,
    ) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise VideoConfigError(
                "ffmpeg is required for M3U8 downloads. Install it with: "
                "sudo apt install ffmpeg"
            )

        self.assert_hls_is_not_drm_protected(source_url, page_url)

        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y" if overwrite else "-n",
            "-user_agent",
            self.config.user_agent,
            "-referer",
            page_url,
        ]

        cookie_header = self.session_cookie_header(source_url)
        if cookie_header:
            command.extend(["-headers", f"Cookie: {cookie_header}\r\n"])

        command.extend(
            [
                "-i",
                source_url,
                "-map",
                "0",
                "-c",
                "copy",
                str(output_path),
            ]
        )
        try:
            subprocess.run(command, check=True)
        except subprocess.CalledProcessError:
            output_path.unlink(missing_ok=True)
            raise

    def assert_hls_is_not_drm_protected(self, source_url: str, page_url: str) -> None:
        headers = self.build_download_headers(page_url)
        response = self.session.get(
            source_url,
            headers=headers,
            timeout=self.config.timeout,
        )
        response.raise_for_status()
        playlist = response.text.lower()
        drm_markers = (
            "method=sample-aes",
            "com.apple.streamingkeydelivery",
            "skd://",
            "edef8ba9-79d6-4ace-a3c8-27dcd51d21ed",
        )
        if any(marker in playlist for marker in drm_markers):
            raise VideoConfigError("DRM-protected HLS streams are not supported.")

    def build_download_headers(self, page_url: str) -> dict[str, str]:
        return {
            "User-Agent": self.config.user_agent,
            "Accept": "*/*",
            "Accept-Language": self.config.accept_language,
            "Referer": page_url,
        }

    def session_cookie_header(self, request_url: str | None = None) -> str:
        if request_url:
            request = requests.Request("GET", request_url)
            prepared = self.session.prepare_request(request)
            return prepared.headers.get("Cookie", "")
        return "; ".join(
            f"{cookie.name}={cookie.value}" for cookie in self.session.cookies
        )

    def scrape_video_urls(self, listing_url: str, max_pages: int | None = None) -> list[str]:
        listing_root_url = self.resolve_url(listing_url)
        pending_pages: list[str] = [listing_root_url]
        seen_pages: set[str] = set()
        video_urls: list[str] = []
        seen_videos: set[str] = set()
        page_count = 0

        while pending_pages:
            next_url = pending_pages.pop(0)
            if next_url in seen_pages:
                continue

            seen_pages.add(next_url)
            page_count += 1
            if max_pages is not None and page_count > max_pages:
                break

            soup = self.fetch_soup(next_url)
            for anchor in soup.select("a[href]"):
                absolute_url = self.normalize_video_url(anchor.get("href", ""))
                if not absolute_url:
                    continue
                if absolute_url not in seen_videos:
                    seen_videos.add(absolute_url)
                    video_urls.append(absolute_url)

            for page_url in self.discover_pagination_urls(
                soup,
                current_url=next_url,
                listing_root_url=listing_root_url,
            ):
                if page_url not in seen_pages and page_url not in pending_pages:
                    pending_pages.append(page_url)

        return video_urls

    def discover_pagination_urls(
        self,
        soup: BeautifulSoup,
        current_url: str,
        listing_root_url: str,
    ) -> list[str]:
        candidates: set[str] = set()
        current_parsed = urlparse(current_url)
        listing_root_parsed = urlparse(listing_root_url)

        next_url = self.find_next_page_url(soup, current_url)
        if next_url and self.is_supported_pagination_url(
            parsed_url=urlparse(next_url),
            current_parsed=current_parsed,
            listing_root_parsed=listing_root_parsed,
        ):
            candidates.add(next_url)

        for anchor in soup.select("a[href]"):
            href = anchor.get("href", "").strip()
            if not href:
                continue

            absolute_url = self.resolve_url(href.split("#", 1)[0])
            parsed_url = urlparse(absolute_url)
            if self.is_supported_pagination_url(
                parsed_url=parsed_url,
                current_parsed=current_parsed,
                listing_root_parsed=listing_root_parsed,
            ):
                candidates.add(absolute_url)

        return sorted(candidates, key=self.pagination_sort_key)

    def find_next_page_url(self, soup: BeautifulSoup, current_url: str) -> str | None:
        selectors = [
            "a[rel='next']",
            "a.pagination__next",
            "a .fh-button__inner-icon-left",
        ]
        for selector in selectors:
            match = soup.select_one(selector)
            if match is None:
                continue
            if match.name == "a":
                href = match.get("href")
            else:
                href = match.parent.get("href") if match.parent else None
            if href:
                return self.resolve_url(href)

        for anchor in soup.select("a[href]"):
            text = anchor.get_text(" ", strip=True).lower()
            aria_label = (anchor.get("aria-label") or "").lower()
            if "next" in text or "next" in aria_label:
                return self.resolve_url(anchor["href"])

        return None

    def is_supported_pagination_url(
        self,
        parsed_url,
        current_parsed,
        listing_root_parsed,
    ) -> bool:
        if parsed_url.netloc != listing_root_parsed.netloc:
            return False
        if parsed_url.path != listing_root_parsed.path:
            return False

        query_params = parse_qs(parsed_url.query)
        current_params = parse_qs(current_parsed.query)
        if query_params == current_params:
            return False

        page_value = self.extract_page_number_from_query(query_params)
        if page_value is None:
            return False

        current_page = self.extract_page_number_from_query(current_params) or 1
        return page_value >= 1 and page_value != current_page

    def extract_page_number_from_query(self, query_params: dict[str, list[str]]) -> int | None:
        for key in ("page", "p"):
            raw_value = query_params.get(key, [])
            if not raw_value:
                continue
            try:
                return int(raw_value[0])
            except (TypeError, ValueError):
                continue
        return None

    def pagination_sort_key(self, url: str) -> tuple[int, str]:
        parsed_url = urlparse(url)
        page_value = self.extract_page_number_from_query(parse_qs(parsed_url.query))
        if page_value is None:
            return (1, url)
        return (page_value, url)

    def normalize_video_url(self, href: str) -> str | None:
        cleaned_href = href.strip()
        if not cleaned_href or "/videos/" not in cleaned_href:
            return None

        absolute_url = self.resolve_url(cleaned_href.split("#", 1)[0])
        parsed_url = urlparse(absolute_url)
        if parsed_url.netloc != urlparse(self.config.base_url).netloc:
            return None
        if not parsed_url.path.startswith("/videos/"):
            return None
        if parsed_url.path in {"/videos/vr"}:
            return None
        return absolute_url


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Requests-based client for FapHouse page inspection and authorized "
            "video-config/download requests."
        )
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to a local JSON config file. Environment variables override it.",
    )
    parser.add_argument(
        "--cookies-json",
        help=(
            "Optional JSON file containing Selenium driver.get_cookies() output. "
            "The config.local.json cookie string is also supported."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect-video",
        help="Fetch a public video page and print its embedded view-state summary.",
    )
    inspect_parser.add_argument("url", help="Absolute or relative video page URL.")
    inspect_parser.add_argument(
        "--raw-view-state",
        action="store_true",
        help="Include the full embedded view-state JSON in the output.",
    )

    config_parser = subparsers.add_parser(
        "video-config",
        help=(
            "Inspect a video page, fetch original-video-config with the current "
            "session cookies, and print stream/download URLs."
        ),
    )
    config_parser.add_argument("url", help="Absolute or relative video page URL.")
    config_parser.add_argument(
        "--video-id",
        help="Optional video ID override when it cannot be extracted from view-state.",
    )
    config_parser.add_argument(
        "--format",
        dest="video_format",
        help="Optional format key such as 720p, 1080p, original, or source.",
    )
    config_parser.add_argument(
        "--raw-config",
        action="store_true",
        help="Include the complete original-video-config response.",
    )

    download_parser = subparsers.add_parser(
        "download-video",
        help="Resolve a video source and download it with the authenticated session.",
    )
    download_parser.add_argument("url", help="Absolute or relative video page URL.")
    download_parser.add_argument(
        "--video-id",
        help="Optional video ID override when it cannot be extracted from view-state.",
    )
    download_parser.add_argument(
        "--format",
        dest="video_format",
        help="Format key to download. Without this option, the highest numeric format is used.",
    )
    download_parser.add_argument(
        "--source",
        choices=("stream", "direct", "auto"),
        default="stream",
        help=(
            "Use the M3U8 stream, direct file, or prefer direct and fall back to "
            "stream. Default: stream."
        ),
    )
    download_parser.add_argument(
        "--output",
        help="Output file path. A title/format based MP4 name is generated by default.",
    )
    download_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing output file.",
    )

    scrape_model_parser = subparsers.add_parser(
        "scrape-model",
        help="Scrape video URLs from a public model/listing page.",
    )
    scrape_model_parser.add_argument("url", help="Absolute or relative model/listing page URL.")
    scrape_model_parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional page limit for pagination traversal.",
    )

    scrape_file_parser = subparsers.add_parser(
        "scrape-file",
        help="Scrape video URLs for each listing URL stored in a text file.",
    )
    scrape_file_parser.add_argument("input_file", help="Text file with one listing URL per line.")
    scrape_file_parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional page limit for each listing URL.",
    )

    show_template_parser = subparsers.add_parser(
        "show-template",
        help="Render a header capture template without sending the request.",
    )
    show_template_parser.add_argument(
        "template",
        choices=sorted(TEMPLATE_PATHS),
        help="Template name to render.",
    )
    show_template_parser.add_argument("--page-url", help="Page URL context for the template.")
    show_template_parser.add_argument("--path", help="Path override for the template.")
    show_template_parser.add_argument("--referer", help="Referer override for the template.")

    return parser


def handle_inspect_video(client: FapClient, args: argparse.Namespace) -> int:
    result = client.inspect_video(args.url)
    if not args.raw_view_state:
        result.pop("view_state", None)
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


def handle_video_config(client: FapClient, args: argparse.Namespace) -> int:
    result = client.fetch_original_video_config(
        args.url,
        video_id=args.video_id,
    )

    output: dict[str, Any] = {
        "page_url": result["page_url"],
        "video_id": result["video_id"],
        "title": result["title"],
        "endpoint": result["endpoint"],
        "stream_formats": result["stream_formats"],
        "download_formats": result["download_formats"],
    }

    if args.video_format:
        for output_key, formats in (
            ("selected_stream", result["stream_formats"]),
            ("selected_download", result["download_formats"]),
        ):
            try:
                output[output_key] = client.select_format(
                    formats,
                    args.video_format,
                )
            except VideoConfigError:
                output[output_key] = None

    if args.raw_config:
        output["raw_config"] = result["raw_config"]

    print(json.dumps(output, indent=2, ensure_ascii=True))
    return 0


def handle_download_video(client: FapClient, args: argparse.Namespace) -> int:
    config_result = client.fetch_original_video_config(
        args.url,
        video_id=args.video_id,
    )
    selected_source = client.resolve_format_source(
        config_result,
        requested_format=args.video_format,
        source_type=args.source,
    )
    output_path = (
        Path(args.output)
        if args.output
        else default_video_output_path(config_result, selected_source)
    )

    print(
        json.dumps(
            {
                "video_id": config_result["video_id"],
                "format": selected_source["format"],
                "source_type": selected_source["source_type"],
                "source_url": selected_source["url"],
                "output": str(output_path.expanduser().resolve()),
            },
            indent=2,
            ensure_ascii=True,
        )
    )

    saved_path = client.download_video_source(
        selected_source,
        page_url=config_result["page_url"],
        output_path=output_path,
        overwrite=args.overwrite,
    )
    print(f"Downloaded: {saved_path}")
    return 0


def handle_scrape_model(client: FapClient, args: argparse.Namespace) -> int:
    result = {
        "listing_url": client.resolve_url(args.url),
        "video_urls": client.scrape_video_urls(args.url, max_pages=args.max_pages),
    }
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


def handle_scrape_file(client: FapClient, args: argparse.Namespace) -> int:
    input_path = Path(args.input_file)
    listing_urls = [
        line.strip()
        for line in input_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    results = []
    for listing_url in listing_urls:
        results.append(
            {
                "listing_url": client.resolve_url(listing_url),
                "video_urls": client.scrape_video_urls(
                    listing_url,
                    max_pages=args.max_pages,
                ),
            }
        )
    print(json.dumps(results, indent=2, ensure_ascii=True))
    return 0


def handle_show_template(client: FapClient, args: argparse.Namespace) -> int:
    result = client.preview_template(
        args.template,
        page_url=args.page_url,
        path=args.path,
        referer=args.referer,
    )
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = ClientConfig.load(args.config)
    except ValueError as exc:
        parser.exit(status=2, message=f"{exc}\n")

    client = FapClient(config)

    if args.cookies_json:
        try:
            cookies = load_selenium_cookie_file(Path(args.cookies_json))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            parser.exit(status=2, message=f"Could not load Selenium cookies: {exc}\n")
        client.import_selenium_cookies(cookies)

    handlers = {
        "inspect-video": handle_inspect_video,
        "video-config": handle_video_config,
        "download-video": handle_download_video,
        "scrape-model": handle_scrape_model,
        "scrape-file": handle_scrape_file,
        "show-template": handle_show_template,
    }

    try:
        return handlers[args.command](client, args)
    except ProtectedEndpointError as exc:
        parser.exit(status=2, message=f"{exc}\n")
    except (VideoConfigError, FileExistsError, subprocess.CalledProcessError) as exc:
        parser.exit(status=1, message=f"Video download error: {exc}\n")
    except requests.HTTPError as exc:
        parser.exit(status=1, message=f"HTTP error: {exc}\n")
    except requests.RequestException as exc:
        parser.exit(status=1, message=f"Request failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())