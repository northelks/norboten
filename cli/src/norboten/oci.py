"""A minimal OCI distribution client: anonymous pull of manifests and blobs.

Enough for public GHCR repositories — golden images and lab artifacts are both plain blobs
addressed by digest. Publishing uses `oras` in CI, not this module.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path

import httpx

MANIFEST_TYPES = ", ".join(
    [
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


class OciError(RuntimeError):
    pass


def split_ref(ref: str) -> tuple[str, str]:
    """'ghcr.io/owner/norboten-base/alpine' -> ('ghcr.io', 'owner/norboten-base/alpine')."""
    host, _, repo = ref.partition("/")
    if not repo or not ("." in host or ":" in host or host == "localhost"):
        raise OciError(f"not a registry reference: {ref!r}")
    return host, repo


class Client:
    def __init__(self, ref: str, timeout: float = 60):
        self.host, self.repo = split_ref(ref)
        # A registry on this machine (tests, a local mirror) speaks plain HTTP.
        local = self.host.split(":")[0] in ("localhost", "127.0.0.1")
        self.scheme = "http" if local else "https"
        self._http = httpx.Client(timeout=timeout, follow_redirects=True)
        self._token: str | None = None

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _authenticate(self, challenge: str) -> None:
        params = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
        realm = params.pop("realm", None)
        if not realm:
            raise OciError(f"unsupported auth challenge from {self.host}: {challenge}")
        params.setdefault("scope", f"repository:{self.repo}:pull")
        r = self._http.get(realm, params=params)
        if r.status_code != 200:
            raise OciError(f"{self.host} refused an anonymous token for {self.repo}")
        body = r.json()
        self._token = body.get("token") or body.get("access_token")

    def _get(self, path: str, *, stream: bool = False, accept: str | None = None):
        url = f"{self.scheme}://{self.host}/v2/{self.repo}/{path}"
        for _ in range(2):
            headers = {"Accept": accept} if accept else {}
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            req = self._http.build_request("GET", url, headers=headers)
            resp = self._http.send(req, stream=stream)
            if resp.status_code == 401 and not self._token:
                challenge = resp.headers.get("www-authenticate", "")
                resp.close()
                self._authenticate(challenge)
                continue
            if resp.status_code == 404:
                resp.close()
                raise OciError(f"{self.host}/{self.repo}: {path} not found")
            if resp.status_code >= 400:
                resp.close()
                raise OciError(f"{self.host}/{self.repo}: {path} -> HTTP {resp.status_code}")
            return resp
        raise OciError(f"{self.host}: authentication failed")

    def manifest(self, tag_or_digest: str) -> dict:
        resp = self._get(f"manifests/{tag_or_digest}", accept=MANIFEST_TYPES)
        return resp.json()

    def download_blob(
        self,
        digest: str,
        dest: Path,
        progress: Callable[[int, int], None] | None = None,
    ) -> None:
        """Stream a blob to dest, verifying its sha256 before the file appears."""
        algo, _, expected = digest.partition(":")
        if algo != "sha256":
            raise OciError(f"unsupported digest {digest}")
        tmp = dest.with_suffix(dest.suffix + ".part")
        h = hashlib.sha256()
        resp = self._get(f"blobs/{digest}", stream=True)
        try:
            total = int(resp.headers.get("content-length", 0))
            with tmp.open("wb") as f:
                for chunk in resp.iter_bytes(1 << 20):
                    f.write(chunk)
                    h.update(chunk)
                    if progress:
                        progress(len(chunk), total)
        finally:
            resp.close()
        if h.hexdigest() != expected:
            tmp.unlink(missing_ok=True)
            raise OciError(f"blob {digest} failed verification — discarded")
        tmp.replace(dest)

    def image_layers(self, tag: str) -> list[dict]:
        """Layer descriptors of an image, resolving a multi-platform index if needed.
        Lab artifacts are platform-independent, so the first real image wins (attestation
        manifests are tagged unknown/unknown and skipped)."""
        m = self.manifest(tag)
        if "manifests" in m:
            real = [d for d in m["manifests"] if d.get("platform", {}).get("os") != "unknown"]
            if not real:
                raise OciError(f"{self.repo}:{tag} has no usable image")
            m = self.manifest(real[0]["digest"])
        return m["layers"]
