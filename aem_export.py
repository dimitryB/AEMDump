#!/usr/bin/env python3
# Copyright (c) 2026 dbur
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import email.utils
import getpass
import logging
import os
import posixpath
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import unquote, urlparse

import requests


DAV_NS = {"d": "DAV:"}


@dataclass(frozen=True)
class DavItem:
    repo_path: str
    is_collection: bool
    content_length: int | None = None
    modified_time: datetime | None = None


class AemWebDavExporter:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        remote_root: str,
        local_root: Path,
        verify_tls: bool = True,
        connect_timeout: int = 10,
        read_timeout: int = 120,
        chunk_size: int = 1024 * 1024,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.remote_root = self._normalize_repo_path(remote_root)
        self.local_root = local_root
        self.timeout = (connect_timeout, read_timeout)
        self.chunk_size = chunk_size

        self.session = requests.Session()
        self.session.auth = (username, password)
        self.session.verify = verify_tls

        self.files_seen = 0
        self.files_downloaded = 0
        self.files_skipped = 0
        self.files_failed = 0
        self.dirs_seen = 0

    def export(self) -> int:
        logging.info("Starting export")
        logging.info("Base URL: %s", self.base_url)
        logging.info("Remote root: %s", self.remote_root)
        logging.info("Local root: %s", self.local_root)

        self.local_root.mkdir(parents=True, exist_ok=True)

        try:
            for item in self.walk(self.remote_root):
                if item.is_collection:
                    self.dirs_seen += 1
                    continue

                self.files_seen += 1
                self._process_file(item)

        except Exception as exc:
            logging.error("Fatal error while exporting %s: %s", self.remote_root, exc, exc_info=True)
            return 2

        logging.info(
            "Done. dirs=%s files_seen=%s downloaded=%s skipped=%s failed=%s",
            self.dirs_seen,
            self.files_seen,
            self.files_downloaded,
            self.files_skipped,
            self.files_failed,
        )

        return 1 if self.files_failed > 0 else 0

    def _process_file(self, item: DavItem) -> None:
        try:
            target = self._target_file_for_repo_path(item.repo_path)
            if target.exists() and target.is_file() and item.content_length is not None:
                local_size = target.stat().st_size
                if local_size == item.content_length:
                    self._apply_file_times(target, item)
                    self.files_skipped += 1
                    logging.info(
                        "SKIP  %s (size match: %s bytes, mtime refreshed=%s)",
                        item.repo_path,
                        local_size,
                        item.modified_time,
                    )
                    return

            self.download_file(item.repo_path, target)
            self._apply_file_times(target, item)
            self.files_downloaded += 1
            logging.info(
                "GET   %s -> %s [modified=%s]",
                item.repo_path,
                target,
                item.modified_time,
            )

        except Exception as exc:
            self.files_failed += 1
            logging.error("FAIL  %s: %s", item.repo_path, exc, exc_info=False)

    def walk(self, repo_path: str) -> Iterator[DavItem]:
        stack = [self._normalize_repo_path(repo_path)]
        while stack:
            current = stack.pop()
            children = self.list_children(current)
            for item in children:
                yield item
            for item in reversed(children):
                if item.is_collection:
                    stack.append(item.repo_path)

    def list_children(self, repo_path: str) -> list[DavItem]:
        repo_path = self._normalize_repo_path(repo_path)
        url = self._url_for_repo_path(repo_path)

        body = """<?xml version="1.0" encoding="utf-8"?>
<D:propfind xmlns:D="DAV:">
  <D:prop>
    <D:resourcetype />
    <D:getcontentlength />
    <D:getlastmodified />
  </D:prop>
</D:propfind>"""

        response = self.session.request(
            method="PROPFIND",
            url=url,
            headers={"Depth": "1", "Content-Type": "text/xml"},
            data=body.encode("utf-8"),
            timeout=self.timeout,
        )
        response.raise_for_status()

        root = ET.fromstring(response.text)
        items: list[DavItem] = []

        for resp in root.findall("d:response", DAV_NS):
            href_el = resp.find("d:href", DAV_NS)
            if href_el is None or not href_el.text:
                continue

            href_path = self._href_to_repo_path(href_el.text)
            href_path = self._normalize_repo_path(href_path)

            if href_path == repo_path:
                continue
            if repo_path != "/" and not href_path.startswith(f"{repo_path}/"):
                logging.warning("Skipping item outside root listing: %s (root=%s)", href_path, repo_path)
                continue

            collection_el = resp.find("d:propstat/d:prop/d:resourcetype/d:collection", DAV_NS)
            is_collection = collection_el is not None

            length_el = resp.find("d:propstat/d:prop/d:getcontentlength", DAV_NS)
            content_length = None
            if length_el is not None and length_el.text:
                try:
                    content_length = int(length_el.text)
                except ValueError:
                    content_length = None

            modified_el = resp.find("d:propstat/d:prop/d:getlastmodified", DAV_NS)
            modified_time = None
            if modified_el is not None and modified_el.text:
                modified_time = self._parse_http_datetime(modified_el.text)

            items.append(
                DavItem(
                    repo_path=href_path,
                    is_collection=is_collection,
                    content_length=content_length,
                    modified_time=modified_time,
                )
            )

        return items

    def download_file(self, repo_path: str, target_file: Path) -> None:
        url = self._url_for_repo_path(repo_path)
        target_file.parent.mkdir(parents=True, exist_ok=True)

        with self.session.get(url, timeout=self.timeout, stream=True) as response:
            response.raise_for_status()
            with target_file.open("wb") as fh:
                for chunk in response.iter_content(chunk_size=self.chunk_size):
                    if chunk:
                        fh.write(chunk)

    def _apply_file_times(self, target_file: Path, item: DavItem) -> None:
        if item.modified_time is None:
            return

        ts = item.modified_time.timestamp()

        try:
            current_stat = target_file.stat()
            os.utime(target_file, (current_stat.st_atime, ts))
        except Exception:
            os.utime(target_file, (ts, ts))

    def _target_file_for_repo_path(self, repo_path: str) -> Path:
        repo_path = self._normalize_repo_path(repo_path)

        if self.remote_root == "/":
            relative = repo_path.lstrip("/")
        elif repo_path.startswith(f"{self.remote_root}/"):
            relative = repo_path[len(self.remote_root) :].lstrip("/")
        else:
            raise ValueError(f"Remote path outside export root: {repo_path}")

        if not relative or relative in {".", ".."}:
            raise ValueError(f"Invalid relative path for export: {repo_path}")

        relative_path = Path(relative)
        if any(part in {"", ".", ".."} for part in relative_path.parts):
            raise ValueError(f"Unsafe relative path for export: {repo_path}")

        target = (self.local_root / relative_path).resolve(strict=False)
        local_root = self.local_root.resolve(strict=False)
        if target == local_root or local_root not in target.parents:
            raise ValueError(f"Resolved path escapes local root: {target}")

        return target

    def _url_for_repo_path(self, repo_path: str) -> str:
        repo_path = self._normalize_repo_path(repo_path)
        return f"{self.base_url}{repo_path}"

    @staticmethod
    def _normalize_repo_path(path: str) -> str:
        normalized = posixpath.normpath("/" + path.strip("/"))
        return "/" if normalized == "." else normalized

    @staticmethod
    def _parse_http_datetime(value: str) -> datetime | None:
        try:
            dt = email.utils.parsedate_to_datetime(value.strip())
            if dt is None:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    def _href_to_repo_path(self, href: str) -> str:
        parsed = urlparse(href)
        path = unquote(parsed.path if parsed.scheme else href)

        prefix = "/crx/repository/crx.default"
        if path.startswith(prefix):
            path = path[len(prefix):]

        return self._normalize_repo_path(path)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy files from AEM via WebDAV to a local directory, preserving modified time from getlastmodified."
    )

    parser.add_argument(
        "--base-url",
        required=True,
        help="AEM WebDAV base URL, e.g. http://host:4502/crx/repository/crx.default",
    )
    parser.add_argument(
        "--username",
        required=True,
        help="AEM username",
    )
    parser.add_argument(
        "--password",
        help="AEM password (less secure on shared systems; prefer --password-env or prompt)",
    )
    parser.add_argument(
        "--password-env",
        default="AEM_PASSWORD",
        help="Environment variable name containing the AEM password, default: AEM_PASSWORD",
    )
    parser.add_argument(
        "--no-password-prompt",
        action="store_true",
        help="Do not prompt for password if not provided via --password/--password-env",
    )
    parser.add_argument(
        "--remote-root",
        default="/content/dam",
        help="Repository path to export, default: /content/dam",
    )
    parser.add_argument(
        "--local-root",
        required=True,
        help="Local destination directory",
    )
    parser.add_argument(
        "--connect-timeout",
        type=int,
        default=10,
        help="Connection timeout in seconds, default: 10",
    )
    parser.add_argument(
        "--read-timeout",
        type=int,
        default=120,
        help="Read timeout in seconds, default: 120",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1024 * 1024,
        help="Download chunk size in bytes, default: 1048576",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level, default: INFO",
    )

    return parser.parse_args(argv)


def resolve_password(args: argparse.Namespace) -> str:
    if args.password:
        return args.password

    env_password = os.environ.get(args.password_env)
    if env_password:
        return env_password

    if args.no_password_prompt or not sys.stdin.isatty():
        raise ValueError(
            f"Password not provided. Set --password, define {args.password_env}, or run with an interactive TTY."
        )

    return getpass.getpass("AEM password: ")


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        password = resolve_password(args)
    except ValueError as exc:
        logging.error(str(exc))
        return 2

    exporter = AemWebDavExporter(
        base_url=args.base_url,
        username=args.username,
        password=password,
        remote_root=args.remote_root,
        local_root=Path(args.local_root),
        verify_tls=not args.insecure,
        connect_timeout=args.connect_timeout,
        read_timeout=args.read_timeout,
        chunk_size=args.chunk_size,
    )

    return exporter.export()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
