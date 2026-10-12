"""Object storage adapters with a single interface.

- LocalStorage: files under LOCAL_STORAGE_DIR (development, single-host deployments
  with a persistent volume).
- SupabaseStorage: Supabase Storage REST API (production). Uses the service-role key
  server-side only; browsers receive short-lived signed URLs from our API, never keys.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol

import httpx

from app.config import get_settings


class Storage(Protocol):
    def put_file(self, key: str, src: Path, content_type: str) -> None: ...
    def put_bytes(self, key: str, data: bytes, content_type: str) -> None: ...
    def local_path(self, key: str) -> Path: ...
    def exists(self, key: str) -> bool: ...
    def delete_prefix(self, prefix: str) -> None: ...
    def delete(self, key: str) -> None: ...


def _safe_key(key: str) -> str:
    parts = [p for p in key.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    if not parts:
        raise ValueError("empty storage key")
    return "/".join(parts)


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / _safe_key(key)).resolve()
        if self.root not in p.parents and p != self.root:
            raise ValueError("storage key escapes root")
        return p

    def put_file(self, key: str, src: Path, content_type: str) -> None:
        dst = self._path(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.resolve() != dst:
            shutil.copyfile(src, dst)

    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        dst = self._path(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)

    def local_path(self, key: str) -> Path:
        return self._path(key)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()

    def delete_prefix(self, prefix: str) -> None:
        p = self._path(prefix)
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()


class SupabaseStorage:
    """Minimal Supabase Storage client. Files are cached locally for processing/serving.

    NOTE: implemented against the documented Supabase Storage REST API but not
    exercised against a live project in this repository's test-suite (no credentials).
    """

    def __init__(self, url: str, service_key: str, bucket: str, cache_dir: Path) -> None:
        self.base = url.rstrip("/") + "/storage/v1"
        self.bucket = bucket
        self.headers = {"Authorization": f"Bearer {service_key}", "apikey": service_key}
        self.cache = LocalStorage(cache_dir)

    def _url(self, key: str) -> str:
        return f"{self.base}/object/{self.bucket}/{_safe_key(key)}"

    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        r = httpx.post(
            self._url(key), content=data, headers={**self.headers, "Content-Type": content_type, "x-upsert": "true"},
            timeout=120,
        )
        r.raise_for_status()
        self.cache.put_bytes(key, data, content_type)

    def put_file(self, key: str, src: Path, content_type: str) -> None:
        self.put_bytes(key, src.read_bytes(), content_type)

    def local_path(self, key: str) -> Path:
        p = self.cache.local_path(key)
        if not p.exists():
            r = httpx.get(self._url(key), headers=self.headers, timeout=300)
            r.raise_for_status()
            self.cache.put_bytes(key, r.content, "application/octet-stream")
        return p

    def exists(self, key: str) -> bool:
        if self.cache.exists(key):
            return True
        r = httpx.head(self._url(key), headers=self.headers, timeout=30)
        return r.status_code == 200

    def delete(self, key: str) -> None:
        httpx.request(
            "DELETE", f"{self.base}/object/{self.bucket}", json={"prefixes": [_safe_key(key)]}, headers=self.headers,
            timeout=60,
        )
        self.cache.delete(key)

    def delete_prefix(self, prefix: str) -> None:
        r = httpx.post(
            f"{self.base}/object/list/{self.bucket}", json={"prefix": _safe_key(prefix), "limit": 1000},
            headers=self.headers, timeout=60,
        )
        if r.status_code == 200:
            keys = [f"{_safe_key(prefix)}/{o['name']}" for o in r.json()]
            if keys:
                httpx.request(
                    "DELETE", f"{self.base}/object/{self.bucket}", json={"prefixes": keys}, headers=self.headers,
                    timeout=60,
                )
        self.cache.delete_prefix(prefix)


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        s = get_settings()
        if s.storage_backend == "supabase":
            if not (s.supabase_url and s.supabase_service_role_key):
                raise RuntimeError("STORAGE_BACKEND=supabase requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
            _storage = SupabaseStorage(
                s.supabase_url, s.supabase_service_role_key, s.supabase_storage_bucket, s.local_storage_dir / "_cache"
            )
        else:
            _storage = LocalStorage(s.local_storage_dir)
    return _storage
