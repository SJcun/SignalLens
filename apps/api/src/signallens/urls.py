"""内容 URL 规范化：为同一资源建立稳定身份。"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMETERS = {
    "entry",
    "fbclid",
    "from",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "referrer",
}


def normalize_content_url(value: str) -> str:
    """移除片段和常见追踪参数，同时保留决定内容身份的查询参数。"""

    url = urlsplit(value.strip())
    scheme = url.scheme.lower()
    hostname = (url.hostname or "").lower()
    port = url.port
    is_default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = hostname if port is None or is_default_port else f"{hostname}:{port}"
    path = url.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(url.query, keep_blank_values=True)
            if key.lower() not in TRACKING_PARAMETERS and not key.lower().startswith("utm_")
        ),
        doseq=True,
    )
    return urlunsplit((scheme, netloc, path, query, ""))
