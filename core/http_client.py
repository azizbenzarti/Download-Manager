# Network comm

from __future__ import annotations

from typing import Dict, Iterator, Optional

import requests


class HttpClient:
    """
    Small HTTP utility class for:
    - fetching file metadata
    - checking range support
    - streaming full or partial content
    """

    def __init__(
        self,
        timeout: int = 15,
        user_agent: str = "SDM/1.0",
    ) -> None:
        self.timeout = timeout
        self.default_headers = {
            "User-Agent": user_agent,
        }

    def get_file_metadata(self, url: str) -> Dict[str, object]:
        """
        Fetch metadata using HEAD request.

        Returns:
            {
                "content_length": int,
                "accept_ranges": bool,
                "content_type": str | None,
                "filename": str | None,
            }
        """
        response = requests.head(
            url,
            headers=self.default_headers,
            allow_redirects=True,
            timeout=self.timeout,
        )
        response.raise_for_status()

        content_length_header = response.headers.get("Content-Length")
        content_length = int(content_length_header) if content_length_header else 0

        accept_ranges_header = response.headers.get("Accept-Ranges", "")
        accept_ranges = accept_ranges_header.lower() == "bytes"

        content_type = response.headers.get("Content-Type")
        filename = self._extract_filename(response)

        return {
            "content_length": content_length,
            "accept_ranges": accept_ranges,
            "content_type": content_type,
            "filename": filename,
        }

    def supports_range_requests(self, url: str) -> bool:
        """
        Convenience wrapper around HEAD metadata.
        """
        metadata = self.get_file_metadata(url)
        return bool(metadata["accept_ranges"])

    def stream_range(
        self,
        url: str,
        start_byte: int,
        end_byte: int,
        chunk_size: int = 8192,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Iterator[bytes]:
        """
        Stream a specific byte range from the remote file.

        Raises:
            requests.HTTPError if server responds with an error status
            ValueError if expected partial content is not returned
        """
        headers = dict(self.default_headers)
        headers["Range"] = f"bytes={start_byte}-{end_byte}"

        if extra_headers:
            headers.update(extra_headers)

        response = requests.get(
            url,
            headers=headers,
            stream=True,
            allow_redirects=True,
            timeout=self.timeout,
        )
        response.raise_for_status()

        # For range requests, 206 Partial Content is the expected response.
        if response.status_code != 206:
            raise ValueError(
                f"Server did not honor range request "
                f"(expected 206, got {response.status_code})."
            )

        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                yield chunk

    def stream_full(
        self,
        url: str,
        chunk_size: int = 8192,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Iterator[bytes]:
        """
        Stream the full file content.
        Useful as fallback when range requests are not supported.
        """
        headers = dict(self.default_headers)
        if extra_headers:
            headers.update(extra_headers)

        response = requests.get(
            url,
            headers=headers,
            stream=True,
            allow_redirects=True,
            timeout=self.timeout,
        )
        response.raise_for_status()

        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                yield chunk

    @staticmethod
    def _extract_filename(response: requests.Response) -> Optional[str]:
        """
        Try to extract filename from Content-Disposition header.
        """
        content_disposition = response.headers.get("Content-Disposition", "")
        if not content_disposition:
            return None

        parts = [part.strip() for part in content_disposition.split(";")]
        for part in parts:
            if part.startswith("filename="):
                return part.split("=", 1)[1].strip('"')

        return None