"""
Shared HTTP mocks for the streaming-based HttpClient (audit R6-20).

`HttpClient.get_text` / `download_bytes` now read bodies via
`client.stream(...)` + `response.iter_raw(...)`. A pre-constructed
`httpx.Response` is already marked as stream-consumed by `Response.__init__`,
so `iter_raw()` would raise `StreamConsumed`. `make_streamable_response`
re-arms the body as a fresh `httpx.ByteStream` so the mock behaves exactly
like a real network response for the streaming read path.
"""

from __future__ import annotations

import httpx


def make_streamable_response(
    status_code: int,
    request: httpx.Request,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
    text: str | None = None,
) -> httpx.Response:
    """Builds a pre-constructed httpx.Response whose body is readable via `iter_raw()`."""
    resp = httpx.Response(
        status_code,
        headers=headers,
        content=content,
        text=text,
        request=request,
    )
    body = resp.content
    resp.stream = httpx.ByteStream(body)
    resp.is_stream_consumed = False
    resp.is_closed = False
    return resp


class StreamContextManager:
    """Mimics the `httpx.Client.stream(...)` context manager around a queued response."""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response

    def __enter__(self) -> httpx.Response:
        return self.response

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class DummyClient:
    """Drop-in `httpx.Client` stub that serves queued responses through `stream()`."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.call_count = 0

    def __enter__(self) -> DummyClient:
        return self

    def __exit__(self, *args) -> None:
        return None

    def stream(self, method: str, url: str, **kwargs) -> StreamContextManager:
        resp = self.responses[self.call_count]
        self.call_count += 1
        return StreamContextManager(resp)
