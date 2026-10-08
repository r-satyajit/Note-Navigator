from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.request
from typing import Any


API_BASE_URL = os.environ.get("NOTES_NAVIGATOR_API_URL", "http://localhost:80").rstrip("/")


class StorageBridgeError(RuntimeError):
    """Raised when the private App Storage API cannot complete an operation."""


class StorageBridge:
    def __init__(self) -> None:
        self._secret = os.environ.get("SESSION_SECRET")
        if not self._secret:
            raise StorageBridgeError(
                "Private storage is not configured. Set SESSION_SECRET for both app services."
            )

    def _post(
        self,
        path: str,
        user_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        timestamp = str(int(time.time()))
        nonce = secrets.token_urlsafe(24)
        body_hash = hashlib.sha256(body).hexdigest()
        signed_message = "\n".join(
            [
                user_id,
                timestamp,
                nonce,
                "POST",
                path,
                body_hash,
            ]
        )
        signature = hmac.new(
            self._secret.encode("utf-8"),
            signed_message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        request = urllib.request.Request(
            f"{API_BASE_URL}{path}",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-NN-User-Id": user_id,
                "X-NN-Timestamp": timestamp,
                "X-NN-Nonce": nonce,
                "X-NN-Signature": signature,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read()
        except urllib.error.HTTPError as error:
            try:
                response_body = error.read()
                detail = json.loads(response_body).get("error", "Storage request failed")
            except (OSError, json.JSONDecodeError, AttributeError):
                detail = "Storage request failed"
            raise StorageBridgeError(str(detail)) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise StorageBridgeError(
                "Private storage could not reach the API service."
            ) from error

        try:
            result = json.loads(data)
        except json.JSONDecodeError as error:
            raise StorageBridgeError("Private storage returned an invalid response.") from error
        if not isinstance(result, dict):
            raise StorageBridgeError("Private storage returned an invalid response.")
        return result

    def upload(
        self,
        *,
        user_id: str,
        space_id: str,
        content: bytes,
        content_type: str,
    ) -> str:
        result = self._post(
            "/api/private-storage/uploads/request-url",
            user_id,
            {
                "contentType": content_type,
                "size": len(content),
                "spaceId": space_id,
            },
        )
        upload_url = result.get("uploadURL")
        object_path = result.get("objectPath")
        if not isinstance(upload_url, str) or not isinstance(object_path, str):
            raise StorageBridgeError("Private storage returned no upload destination.")

        put_request = urllib.request.Request(
            upload_url,
            data=content,
            headers={"Content-Type": content_type},
            method="PUT",
        )
        try:
            with urllib.request.urlopen(put_request, timeout=180) as response:
                if response.status < 200 or response.status >= 300:
                    raise StorageBridgeError("The document could not be uploaded.")
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise StorageBridgeError("The document could not be uploaded.") from error

        try:
            commit_result = self._post(
                "/api/private-storage/uploads/commit",
                user_id,
                {"objectPath": object_path},
            )
            if commit_result.get("success") is not True:
                raise StorageBridgeError("Private storage could not secure the uploaded file.")
        except Exception:
            try:
                self._post(
                    "/api/private-storage/uploads/abort",
                    user_id,
                    {"objectPath": object_path},
                )
            except Exception:
                pass
            raise
        return object_path

    def download(self, *, user_id: str, object_path: str) -> bytes:
        result = self._post(
            "/api/private-storage/download-url",
            user_id,
            {"objectPath": object_path},
        )
        download_url = result.get("downloadURL")
        if not isinstance(download_url, str):
            raise StorageBridgeError("Private storage returned no download URL.")
        try:
            with urllib.request.urlopen(download_url, timeout=120) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise StorageBridgeError("The stored document could not be downloaded.") from error

    def delete(self, *, user_id: str, object_path: str) -> None:
        result = self._post(
            "/api/private-storage/delete",
            user_id,
            {"objectPath": object_path},
        )
        if result.get("success") is not True:
            raise StorageBridgeError("The stored file could not be deleted.")
