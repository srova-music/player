"""Bounded Qobuz catalog/service request primitives.

This module is intentionally provider-specific. It owns request signing,
candidate app-secret validation, bounded retry/error handling, authentication
headers, and pagination bounds.

It performs no UI, playback, queue, normalization, or provider routing work.

The request/signing behaviour is independently adapted from the MIT-licensed
``vicrodh/qbz`` project at commit
``aa5690e4491507976b56a982025eb4b38ec8e064``.
"""

import threading
import time

import requests

from backend.qobuz_cmaf import compute_request_signature


class QobuzCatalogError(RuntimeError):
    """Safe typed failure from the Qobuz catalog/service layer."""

    def __init__(
        self,
        code,
        message,
        *,
        http_status=None,
        retry_after=None,
        transient=False,
    ):
        super().__init__(str(message))
        self.code = str(code)
        self.http_status = (
            int(http_status)
            if http_status is not None
            else None
        )
        self.retry_after = (
            int(retry_after)
            if retry_after is not None
            else None
        )
        self.transient = bool(transient)

    def safe_payload(self):
        payload = {
            "ok": False,
            "error": self.code,
            "message": str(self),
            "transient": self.transient,
        }

        if self.http_status is not None:
            payload["http_status"] = self.http_status

        if self.retry_after is not None:
            payload["retry_after"] = self.retry_after

        return payload


class QobuzCatalogClient:
    """Small authenticated Qobuz service request client."""

    CONNECT_TIMEOUT_SECONDS = 10
    READ_TIMEOUT_SECONDS = 30

    DEFAULT_PAGE_LIMIT = 50
    MAX_PAGE_LIMIT = 100
    MAX_PAGE_OFFSET = 1_000_000

    MAX_ATTEMPTS = 2
    RETRY_DELAY_SECONDS = 0.25
    RETRYABLE_HTTP_STATUSES = frozenset((502, 503, 504))

    SECRET_TEST_TRACK_ID = 5966783
    SECRET_TEST_FORMAT_ID = 5
    SECRET_TEST_PATH = "/track/getFileUrl"
    SECRET_TEST_METHOD = "trackgetFileUrl"

    def __init__(
        self,
        *,
        http_session,
        api_base_url,
        metadata_loader,
        token_loader,
        now=None,
        sleep=None,
    ):
        self._http = http_session
        self._api_base_url = str(api_base_url).rstrip("/")
        self._metadata_loader = metadata_loader
        self._token_loader = token_loader
        self._now = now or time.time
        self._sleep = sleep or time.sleep

        self._secret_lock = threading.Lock()
        self._validated_secret = None
        self._validated_bundle_identity = None

    @classmethod
    def page_bounds(
        cls,
        limit=None,
        offset=None,
        *,
        default_limit=None,
        maximum_limit=None,
    ):
        if default_limit is None:
            default_limit = cls.DEFAULT_PAGE_LIMIT

        if maximum_limit is None:
            maximum_limit = cls.MAX_PAGE_LIMIT

        try:
            page_limit = (
                int(default_limit)
                if limit is None
                else int(limit)
            )
            page_offset = 0 if offset is None else int(offset)
            max_limit = int(maximum_limit)
        except (TypeError, ValueError) as exc:
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz pagination values must be integers.",
            ) from exc

        if max_limit < 1:
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz pagination maximum is invalid.",
            )

        if not 1 <= page_limit <= max_limit:
            raise QobuzCatalogError(
                "invalid_request",
                f"Qobuz page limit must be between 1 and {max_limit}.",
            )

        if not 0 <= page_offset <= cls.MAX_PAGE_OFFSET:
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz page offset is outside the supported range.",
            )

        return page_limit, page_offset

    @staticmethod
    def _valid_ascii_secret(value):
        return (
            isinstance(value, str)
            and value == value.strip()
            and 1 <= len(value) <= 512
            and value.isascii()
            and not any(
                ord(char) <= 32 or ord(char) == 127
                for char in value
            )
        )

    @staticmethod
    def _valid_token(value):
        return (
            isinstance(value, str)
            and value == value.strip()
            and 1 <= len(value) <= 8192
            and value.isascii()
            and not any(
                ord(char) <= 32 or ord(char) == 127
                for char in value
            )
        )

    @staticmethod
    def _normalise_params(params):
        if params is None:
            return {}

        if not isinstance(params, dict):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz request parameters must be a dictionary.",
            )

        result = {}

        for key, value in params.items():
            key = str(key)

            if not key:
                raise QobuzCatalogError(
                    "invalid_request",
                    "Qobuz request parameter name is empty.",
                )

            if value is None:
                continue

            result[key] = str(value)

        return result

    @staticmethod
    def _bundle_identity(metadata):
        return (
            str(metadata.get("bundle_url") or ""),
            str(metadata.get("bundle_version") or ""),
        )

    def _load_metadata(self):
        metadata = self._metadata_loader()

        if not isinstance(metadata, dict):
            raise QobuzCatalogError(
                "provider_unavailable",
                "Qobuz service metadata is unavailable.",
                transient=True,
            )

        app_id = str(metadata.get("app_id") or "").strip()
        secrets_list = metadata.get("app_secrets")

        if not app_id or not app_id.isascii():
            raise QobuzCatalogError(
                "provider_unavailable",
                "Qobuz application metadata is invalid.",
            )

        if (
            not isinstance(secrets_list, (list, tuple))
            or not secrets_list
            or not all(
                self._valid_ascii_secret(secret)
                for secret in secrets_list
            )
        ):
            raise QobuzCatalogError(
                "provider_unavailable",
                "Qobuz catalog signing metadata is unavailable.",
            )

        return metadata

    def _load_unsigned_metadata(self):
        """Load only the metadata required by an unsigned API request."""
        metadata = self._metadata_loader()

        if not isinstance(metadata, dict):
            raise QobuzCatalogError(
                "provider_unavailable",
                "Qobuz service metadata is unavailable.",
                transient=True,
            )

        app_id = str(
            metadata.get("app_id") or ""
        ).strip()

        if not app_id or not app_id.isascii():
            raise QobuzCatalogError(
                "provider_unavailable",
                "Qobuz application metadata is invalid.",
            )

        return metadata

    def _token(self, require_auth):
        token = self._token_loader()

        if token is not None and not self._valid_token(token):
            token = None

        if require_auth and token is None:
            raise QobuzCatalogError(
                "not_authenticated",
                "Qobuz authentication is required.",
                http_status=401,
            )

        return token

    @staticmethod
    def _headers(app_id, token=None):
        headers = {"X-App-Id": str(app_id)}

        if token:
            headers["X-User-Auth-Token"] = str(token)

        return headers

    def _url(self, path):
        path = str(path or "")

        if (
            not path.startswith("/")
            or "://" in path
            or "\r" in path
            or "\n" in path
        ):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz endpoint path is invalid.",
            )

        return self._api_base_url + path

    def _timestamp(self):
        try:
            timestamp = int(self._now())
        except (TypeError, ValueError) as exc:
            raise QobuzCatalogError(
                "provider_unavailable",
                "Qobuz request clock is unavailable.",
            ) from exc

        if timestamp <= 0:
            raise QobuzCatalogError(
                "provider_unavailable",
                "Qobuz request clock is invalid.",
            )

        return timestamp

    @staticmethod
    def _retry_after(response):
        headers = getattr(response, "headers", None)

        if not headers:
            return None

        value = headers.get("Retry-After")

        try:
            seconds = int(value)
        except (TypeError, ValueError):
            return None

        if 0 <= seconds <= 3600:
            return seconds

        return None

    def _network_get(self, url, *, headers, params):
        return self._http.get(
            url,
            headers=headers,
            params=params,
            timeout=(
                self.CONNECT_TIMEOUT_SECONDS,
                self.READ_TIMEOUT_SECONDS,
            ),
        )

    def _network_post_json(
        self,
        url,
        *,
        headers,
        params,
        json_body,
    ):
        return self._http.post(
            url,
            headers=headers,
            params=params,
            json=json_body,
            timeout=(
                self.CONNECT_TIMEOUT_SECONDS,
                self.READ_TIMEOUT_SECONDS,
            ),
        )

    def _test_secret(self, metadata, token, secret):
        timestamp = self._timestamp()

        arguments = {
            "format_id": str(self.SECRET_TEST_FORMAT_ID),
            "intent": "stream",
            "track_id": str(self.SECRET_TEST_TRACK_ID),
        }

        signature = compute_request_signature(
            self.SECRET_TEST_METHOD,
            arguments,
            timestamp,
            secret,
        )

        query = dict(arguments)
        query["request_ts"] = str(timestamp)
        query["request_sig"] = signature

        try:
            response = self._network_get(
                self._url(self.SECRET_TEST_PATH),
                headers=self._headers(
                    metadata["app_id"],
                    token,
                ),
                params=query,
            )
        except requests.exceptions.Timeout as exc:
            raise QobuzCatalogError(
                "timeout",
                "Qobuz secret validation timed out.",
                transient=True,
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise QobuzCatalogError(
                "provider_unavailable",
                "Qobuz secret validation could not reach the service.",
                transient=True,
            ) from exc

        # Pinned QBZ treats HTTP 400 as an invalid candidate secret.
        return int(response.status_code) != 400

    def _secret(self, metadata, token):
        identity = self._bundle_identity(metadata)

        with self._secret_lock:
            if (
                self._validated_secret is not None
                and self._validated_bundle_identity == identity
            ):
                return self._validated_secret

            self._validated_secret = None
            self._validated_bundle_identity = None

            for candidate in metadata["app_secrets"]:
                if self._test_secret(
                    metadata,
                    token,
                    candidate,
                ):
                    self._validated_secret = candidate
                    self._validated_bundle_identity = identity
                    return candidate

        raise QobuzCatalogError(
            "provider_unavailable",
            "Qobuz catalog signing metadata was rejected.",
        )

    def clear_validated_secret(self):
        with self._secret_lock:
            self._validated_secret = None
            self._validated_bundle_identity = None

    def request_json(
        self,
        path,
        *,
        method_name,
        params=None,
        signature_params=None,
        require_auth=False,
        signed=True,
    ):
        method_name = str(method_name or "").strip()

        if (
            not method_name
            or not method_name.isascii()
            or not method_name.replace("_", "").isalnum()
        ):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz request method name is invalid.",
            )

        if not isinstance(signed, bool):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz request signing mode is invalid.",
            )

        if not signed and signature_params is not None:
            raise QobuzCatalogError(
                "invalid_request",
                "Unsigned Qobuz requests cannot define signature parameters.",
            )

        request_params = self._normalise_params(params)
        token = self._token(bool(require_auth))

        if signed:
            if signature_params is None:
                signing_params = dict(request_params)
            else:
                signing_params = self._normalise_params(
                    signature_params
                )

            metadata = self._load_metadata()
            secret = self._secret(metadata, token)

            timestamp = self._timestamp()

            signature = compute_request_signature(
                method_name,
                signing_params,
                timestamp,
                secret,
            )

            query = dict(request_params)
            query["request_ts"] = str(timestamp)
            query["request_sig"] = signature
        else:
            metadata = self._load_unsigned_metadata()
            query = dict(request_params)

        url = self._url(path)

        headers = self._headers(
            metadata["app_id"],
            token,
        )

        attempt = 0

        while True:
            attempt += 1

            try:
                response = self._network_get(
                    url,
                    headers=headers,
                    params=query,
                )
            except requests.exceptions.Timeout as exc:
                if attempt < self.MAX_ATTEMPTS:
                    self._sleep(self.RETRY_DELAY_SECONDS)
                    continue

                raise QobuzCatalogError(
                    "timeout",
                    "Qobuz request timed out.",
                    transient=True,
                ) from exc
            except requests.exceptions.RequestException as exc:
                if attempt < self.MAX_ATTEMPTS:
                    self._sleep(self.RETRY_DELAY_SECONDS)
                    continue

                raise QobuzCatalogError(
                    "provider_unavailable",
                    "Qobuz service could not be reached.",
                    transient=True,
                ) from exc

            status = int(response.status_code)

            if (
                status in self.RETRYABLE_HTTP_STATUSES
                and attempt < self.MAX_ATTEMPTS
            ):
                self._sleep(self.RETRY_DELAY_SECONDS)
                continue

            if 200 <= status < 300:
                try:
                    payload = response.json()
                except (TypeError, ValueError) as exc:
                    raise QobuzCatalogError(
                        "malformed_response",
                        "Qobuz returned an invalid response.",
                        http_status=status,
                    ) from exc

                if not isinstance(payload, (dict, list)):
                    raise QobuzCatalogError(
                        "malformed_response",
                        "Qobuz returned an unexpected response.",
                        http_status=status,
                    )

                return payload

            if status == 400:
                raise QobuzCatalogError(
                    "invalid_request",
                    "Qobuz rejected the request.",
                    http_status=status,
                )

            if status == 401:
                raise QobuzCatalogError(
                    "not_authenticated",
                    "Qobuz authentication was rejected.",
                    http_status=status,
                )

            if status == 403:
                raise QobuzCatalogError(
                    "unavailable",
                    "Qobuz denied access to this resource.",
                    http_status=status,
                )

            if status == 404:
                raise QobuzCatalogError(
                    "not_found",
                    "The requested Qobuz resource was not found.",
                    http_status=status,
                )

            if status == 429:
                raise QobuzCatalogError(
                    "rate_limited",
                    "Qobuz temporarily rate limited the request.",
                    http_status=status,
                    retry_after=self._retry_after(response),
                    transient=True,
                )

            if status >= 500:
                raise QobuzCatalogError(
                    "provider_unavailable",
                    "Qobuz service is temporarily unavailable.",
                    http_status=status,
                    transient=True,
                )

            raise QobuzCatalogError(
                "provider_error",
                "Qobuz rejected the service request.",
                http_status=status,
            )
    def request_json_post(
        self,
        path,
        *,
        method_name,
        json_body,
        signature_params=None,
        require_auth=False,
    ):
        """
        Issue one bounded signed JSON POST used only for read-only
        provider catalog operations such as track/getList.
        """
        method_name = str(method_name or "").strip()

        if (
            not method_name
            or not method_name.isascii()
            or not method_name.replace("_", "").isalnum()
        ):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz request method name is invalid.",
            )

        if not isinstance(json_body, dict):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz POST body must be a dictionary.",
            )

        signing_params = self._normalise_params(
            signature_params
        )

        token = self._token(bool(require_auth))
        metadata = self._load_metadata()
        secret = self._secret(metadata, token)
        timestamp = self._timestamp()

        signature = compute_request_signature(
            method_name,
            signing_params,
            timestamp,
            secret,
        )

        query = {
            "request_ts": str(timestamp),
            "request_sig": signature,
        }

        url = self._url(path)

        headers = self._headers(
            metadata["app_id"],
            token,
        )

        attempt = 0

        while True:
            attempt += 1

            try:
                response = self._network_post_json(
                    url,
                    headers=headers,
                    params=query,
                    json_body=json_body,
                )
            except requests.exceptions.Timeout as exc:
                if attempt < self.MAX_ATTEMPTS:
                    self._sleep(
                        self.RETRY_DELAY_SECONDS
                    )
                    continue

                raise QobuzCatalogError(
                    "timeout",
                    "Qobuz request timed out.",
                    transient=True,
                ) from exc
            except requests.exceptions.RequestException as exc:
                if attempt < self.MAX_ATTEMPTS:
                    self._sleep(
                        self.RETRY_DELAY_SECONDS
                    )
                    continue

                raise QobuzCatalogError(
                    "provider_unavailable",
                    "Qobuz service could not be reached.",
                    transient=True,
                ) from exc

            status = int(response.status_code)

            if (
                status in self.RETRYABLE_HTTP_STATUSES
                and attempt < self.MAX_ATTEMPTS
            ):
                self._sleep(
                    self.RETRY_DELAY_SECONDS
                )
                continue

            if 200 <= status < 300:
                try:
                    payload = response.json()
                except (TypeError, ValueError) as exc:
                    raise QobuzCatalogError(
                        "malformed_response",
                        "Qobuz returned an invalid response.",
                        http_status=status,
                    ) from exc

                if not isinstance(
                    payload,
                    (dict, list),
                ):
                    raise QobuzCatalogError(
                        "malformed_response",
                        "Qobuz returned an unexpected response.",
                        http_status=status,
                    )

                return payload

            if status == 400:
                raise QobuzCatalogError(
                    "invalid_request",
                    "Qobuz rejected the request.",
                    http_status=status,
                )

            if status == 401:
                raise QobuzCatalogError(
                    "not_authenticated",
                    "Qobuz authentication was rejected.",
                    http_status=status,
                )

            if status == 403:
                raise QobuzCatalogError(
                    "unavailable",
                    "Qobuz denied access to this resource.",
                    http_status=status,
                )

            if status == 404:
                raise QobuzCatalogError(
                    "not_found",
                    "The requested Qobuz resource was not found.",
                    http_status=status,
                )

            if status == 429:
                raise QobuzCatalogError(
                    "rate_limited",
                    "Qobuz temporarily rate limited the request.",
                    http_status=status,
                    retry_after=self._retry_after(
                        response
                    ),
                    transient=True,
                )

            if status >= 500:
                raise QobuzCatalogError(
                    "provider_unavailable",
                    "Qobuz service is temporarily unavailable.",
                    http_status=status,
                    transient=True,
                )

            raise QobuzCatalogError(
                "provider_error",
                "Qobuz rejected the service request.",
                http_status=status,
            )
