"""The GCS backend through the real google-cloud-storage library, against a
fake HTTP transport that answers like a bucket without object versioning.

The mock-based tests in test_storage_gcp.py can't see how the library builds
its requests. A Blob returned by get_blob(), for example, asks for its own
generation by number. Once the object is overwritten, a non-versioned bucket
answers that with 404, so a conditional download or delete through it
reported a lost race as "gone" instead of retrying.
"""

import io
import json
import secrets
import urllib.parse

import pytest
import requests
import urllib3
from google.auth.credentials import AnonymousCredentials
from google.auth.transport.requests import AuthorizedSession
from google.cloud import storage

from whisper import AttrDict, secret
from whisper.storage.gcp import gcs


def _error(code):
    return json.dumps({"error": {"code": code, "message": f"fake {code}"}}).encode()


class FakeBucket(requests.adapters.HTTPAdapter):
    """One object in a non-versioned bucket, served over the JSON API.
    ``race(method, query)`` runs before each request is answered, so a test
    can let a concurrent write in between two requests."""

    def __init__(self, name, content):
        super().__init__()
        self.name = name
        self.generation = 1
        self.content = content
        self.race = lambda method, query: None
        self.log = []

    def overwrite(self, content):
        self.generation += 1
        self.content = content

    def send(self, request, **kwargs):
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(request.url).query))
        self.log.append((request.method, query))
        self.race(request.method, query)
        status, body = self._answer(request, query)
        content_type = "application/octet-stream" if query.get("alt") == "media" else "application/json"
        # a real urllib3 response: downloads read it directly
        raw = urllib3.HTTPResponse(
            body=io.BytesIO(body), status=status, preload_content=False,
            headers={"Content-Type": content_type, "Content-Length": str(len(body))},
        )
        return self.build_response(request, raw)

    def _answer(self, request, query):
        live = self.content is not None
        current = str(self.generation) if live else "0"
        if request.method == "POST":  # upload_from_string(): a multipart upload
            if query.get("ifGenerationMatch") not in (None, current):
                return 412, _error(412)
            content_type = request.headers["Content-Type"]
            if isinstance(content_type, str):
                content_type = content_type.encode()
            boundary = content_type.split(b"boundary=")[1].strip(b'"')
            media_part = request.body.split(b"--" + boundary)[2]
            self.overwrite(media_part.split(b"\r\n\r\n", 1)[1].rstrip(b"\r\n"))
            return 200, json.dumps(self._resource()).encode()
        # asking for a generation by number: gone once it's overwritten
        if not live or query.get("generation") not in (None, current):
            return 404, _error(404)
        if query.get("ifGenerationMatch") not in (None, current):
            return 412, _error(412)
        if request.method == "DELETE":
            self.content = None
            return 204, b""
        if query.get("alt") == "media":
            return 200, self.content
        return 200, json.dumps(self._resource()).encode()

    def _resource(self):
        quoted = urllib.parse.quote(self.name, safe="")
        return {
            "kind": "storage#object", "bucket": "b", "name": self.name,
            "generation": str(self.generation), "metageneration": "1",
            "mediaLink": f"https://storage.googleapis.com/download/storage/v1/b/b/o/{quoted}"
                         f"?generation={self.generation}&alt=media",
        }


@pytest.fixture
def gcs_backend():
    s = secret()
    s.create(secret_id=secrets.token_hex(32), expiration="1 hour", auth="a" * 64, key="k",
             data="ciphertext")
    fake = FakeBucket(f"secrets/{s.id}.json", json.dumps(s.__dict__).encode())
    # the session type the library uses itself, with the fake bucket as its transport
    session = AuthorizedSession(AnonymousCredentials())
    session.mount("https://", fake)
    client = storage.Client(project="p", credentials=AnonymousCredentials(), _http=session)
    b = gcs()
    b.config = AttrDict({"bucket_name": "b", "bucket_path": "secrets", "gcp_project": "p"})
    b.client = client
    b.bucket = client.bucket("b")
    return b, fake, s


def _stored(fake):
    return json.loads(fake.content)


def _overwrite_once(fake, method, alt=None, **changes):
    """A wrong-password write landing just before the first such request."""
    done = []

    def race(m, query):
        if not done and m == method and query.get("alt") == alt:
            done.append(True)
            fake.overwrite(json.dumps(dict(_stored(fake), **changes)).encode())

    fake.race = race


def test_claim_works_once(gcs_backend):
    backend, fake, s = gcs_backend
    assert backend.claim_secret(s.id) is True
    assert fake.content is None
    assert backend.claim_secret(s.id) is False


def test_claim_after_an_overwrite_retries_instead_of_reporting_gone(gcs_backend):
    backend, fake, s = gcs_backend
    _overwrite_once(fake, "DELETE", failed_attempts=1)
    assert backend.claim_secret(s.id) is True
    assert fake.content is None
    assert not any("generation" in query for _, query in fake.log)


def test_wrong_password_count_after_an_overwrite_mid_read(gcs_backend):
    backend, fake, s = gcs_backend
    _overwrite_once(fake, "GET", alt="media", failed_attempts=5)
    assert backend.increment_failed_attempts(s) is True
    assert s.failed_attempts == 6
    assert _stored(fake)["failed_attempts"] == 6


def test_wrong_password_count_after_an_overwrite_before_the_write(gcs_backend):
    """Also a wipe: the count goes on top of it, the ciphertext stays gone."""
    backend, fake, s = gcs_backend
    _overwrite_once(fake, "POST", failed_attempts=10, data="", hash="")
    assert backend.increment_failed_attempts(s) is True
    stored = _stored(fake)
    assert (stored["failed_attempts"], stored["data"], stored["hash"]) == (11, "", "")
    assert not any("generation" in query for _, query in fake.log)


def test_wrong_password_count_for_a_claimed_secret(gcs_backend):
    backend, fake, s = gcs_backend
    assert backend.claim_secret(s.id) is True
    assert backend.increment_failed_attempts(s) is False
    assert fake.content is None  # not recreated
