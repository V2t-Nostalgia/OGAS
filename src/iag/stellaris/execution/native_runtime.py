"""Private client for a platform-native Stellaris in-process runtime.

The runtime describes the semantic tools compiled from ``actions/*.cpp``.
Applications never consume this transport directly: the Broker intersects the
runtime manifest with its authority and semantic contracts first.
"""

from __future__ import annotations

import json
import os
import re
import socket
import stat
import subprocess
import threading
import time
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import ConfigDict, Field, model_validator

from iag.core.contracts import FrozenContract
from iag.core.paths import project_root

LINUX_NATIVE_RUNTIME_BUILD_ID: Final = "121ecb516cbc5f1d39917fbcc36620534384e2c2"
WINDOWS_NATIVE_RUNTIME_BUILD_ID: Final = (
    "sha256:400df27c82ddc845aa9dce79bd468d81f18f060d299cd263e3afa93aef4f7a83"
)
# Compatibility name retained for fixtures written before platform profiles.
NATIVE_RUNTIME_BUILD_ID: Final = LINUX_NATIVE_RUNTIME_BUILD_ID
SUPPORTED_NATIVE_RUNTIME_BUILD_IDS: Final = frozenset(
    {LINUX_NATIVE_RUNTIME_BUILD_ID, WINDOWS_NATIVE_RUNTIME_BUILD_ID}
)
DEFAULT_NATIVE_RUNTIME_SOCKET: Final = Path("/tmp/iag-stellaris-native.sock")
DEFAULT_NATIVE_RUNTIME_PIPE: Final = r"\\.\pipe\iag-stellaris-native"
_PROTOCOL_VERSION: Final = "IAG1"
_DESCRIBE_ACTION: Final = "describe_tools"
_INSPECT_OPEN_EVENTS_ACTION: Final = "inspect_open_events"
_INSPECT_PENDING_DIPLOMATIC_ACTIONS_ACTION: Final = "inspect_pending_diplomatic_actions"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
_TECHNOLOGY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_MAX_RESPONSE_BYTES = 65_536


class NativeRuntimeError(RuntimeError):
    """The native runtime was unavailable or violated its private contract."""


class NativeRuntimeOutcome(StrEnum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    FAILED = "failed"
    PENDING = "pending"
    CONFLICT = "conflict"
    BUSY = "busy"


class NativeRuntimeParameter(FrozenContract):
    """One ordered semantic argument accepted by an action implementation."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        populate_by_name=True,
    )

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    parameter_type: Literal["uint32", "uint64", "string", "boolean"] = Field(
        alias="type"
    )
    required: bool
    description: str = Field(min_length=1, max_length=500)
    minimum: int | None = Field(default=None, ge=0)
    maximum: int | None = Field(default=None, ge=0)
    maximum_length: int | None = Field(default=None, ge=1, le=60_000)

    @model_validator(mode="after")
    def validate_type_limits(self) -> NativeRuntimeParameter:
        if self.parameter_type in {"uint32", "uint64"}:
            if self.minimum is None or self.maximum is None:
                raise ValueError(
                    f"{self.parameter_type} runtime parameters require numeric bounds."
                )
            type_maximum = (
                0xFFFFFFFF if self.parameter_type == "uint32" else 0xFFFFFFFFFFFFFFFF
            )
            if self.maximum > type_maximum or self.minimum > self.maximum:
                raise ValueError(
                    f"Invalid {self.parameter_type} runtime parameter bounds."
                )
        elif self.parameter_type == "string" and self.maximum_length is None:
            raise ValueError("String runtime parameters require maximum_length.")
        return self

    def encode(self, value: object) -> str:
        if self.parameter_type in {"uint32", "uint64"}:
            if isinstance(value, bool) or not isinstance(value, int):
                raise NativeRuntimeError(f"{self.name} must be an integer.")
            minimum = int(self.minimum or 0)
            maximum = int(self.maximum or 0)
            if value < minimum or value > maximum:
                raise NativeRuntimeError(f"{self.name} is outside runtime bounds.")
            return str(value)
        if self.parameter_type == "boolean":
            if not isinstance(value, bool):
                raise NativeRuntimeError(f"{self.name} must be a boolean.")
            return "1" if value else "0"
        if not isinstance(value, str):
            raise NativeRuntimeError(f"{self.name} must be a string.")
        maximum = int(self.maximum_length or 0)
        if not value or len(value) > maximum or "\t" in value or "\n" in value:
            raise NativeRuntimeError(f"{self.name} is not a valid runtime string.")
        return value


class NativeRuntimeTool(FrozenContract):
    """Self-described compiled semantic action."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    action_type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    action_version: int = Field(ge=1)
    application_id: str = Field(default="etc", pattern=r"^[a-z][a-z0-9_]{1,63}$")
    description: str = Field(min_length=1, max_length=500)
    risk_class: Literal[
        "state_change",
        "destructive_state_change",
        "irreversible_state_change",
        "state_change_requires_fresh_save",
    ]
    verification_state: Literal[
        "live_verified", "build_validation_pending", "paired_capture"
    ]
    parameters: tuple[NativeRuntimeParameter, ...]

    @model_validator(mode="after")
    def validate_unique_parameters(self) -> NativeRuntimeTool:
        names = tuple(item.name for item in self.parameters)
        if len(names) != len(set(names)):
            raise ValueError("Runtime tool parameter names must be unique.")
        if any(not item.required for item in self.parameters[:-1]):
            raise ValueError("Optional runtime parameters must follow required ones.")
        return self

    @property
    def semantic_capability(self) -> str:
        return f"stellaris.action.{self.action_type}.v{self.action_version}"


class NativeRuntimeManifest(FrozenContract):
    """Versioned tool catalog emitted by one loaded runtime build."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["iag.native_tool_manifest.v1"]
    platform: Literal["linux-x86_64", "windows-x64"]
    game_version: str = Field(min_length=1, max_length=120)
    build_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    tools: tuple[NativeRuntimeTool, ...]

    @model_validator(mode="after")
    def validate_catalog(self) -> NativeRuntimeManifest:
        keys = tuple((item.action_type, item.action_version) for item in self.tools)
        if len(keys) != len(set(keys)):
            raise ValueError("Runtime manifest contains duplicate actions.")
        return self

    def get(self, action_type: str, action_version: int = 1) -> NativeRuntimeTool:
        for tool in self.tools:
            if (
                tool.action_type == action_type
                and tool.action_version == action_version
            ):
                return tool
        raise KeyError(f"Runtime does not expose {action_type}.v{action_version}.")


class NativeRuntimeResponse(FrozenContract):
    """Strictly parsed evidence returned by the in-process runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: str = Field(min_length=1, max_length=96)
    action: str = Field(min_length=1, max_length=64)
    outcome: NativeRuntimeOutcome
    build_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    country_id: int = Field(ge=0)
    target_echo: str = Field(min_length=1, max_length=60_000)
    detail: str = Field(max_length=240)

    @property
    def technology_id(self) -> str | None:
        """Compatibility view for the original research-only runtime client."""

        return self.target_echo if self.action == "stop_research" else None


class NativeOpenEventOption(FrozenContract):
    """One option currently legal for a native open event."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    option_index: int = Field(ge=0, le=63)
    text_key: str = Field(max_length=512)


class NativeRecoveredCommandCatalog(FrozenContract):
    """Research-only SDK directory; deliberately not a Broker tool manifest."""

    schema_version: Literal["iag.recovered_command_catalog.v1"]
    build_id: str
    process_id: int = Field(gt=0)
    instance_id: int = Field(gt=0)
    probe_revision: int = Field(default=1, ge=1)
    commands: tuple[str, ...]
    native_candidate_commands: tuple[str, ...] = ()
    sdk_fingerprint: str = ""


class NativeProbeBinding(FrozenContract):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    field: str
    storage_kind: Literal[
        "ref",
        "u32",
        "bool",
        "i32",
        "i64",
        "string",
        "definition_pointer",
        "reference_array",
        "game_date32",
        "native_text_value",
    ]
    reference_type: str
    value: int = Field(ge=-(1 << 63), le=(1 << 63) - 1)
    text_value: str = Field(default="", max_length=512)
    reference_ids: tuple[Annotated[int, Field(ge=0, le=0xFFFFFFFF)], ...] = Field(
        default=(), max_length=16
    )

    @model_validator(mode="after")
    def check_storage_range(self) -> NativeProbeBinding:
        # Existing i32 reports carry uint32 bit patterns; only i64 is signed.
        if self.storage_kind != "i64" and not 0 <= self.value <= 0xFFFFFFFF:
            raise ValueError("Non-i64 probe values require an unsigned 32-bit representation.")
        return self


class NativeCommandValidation(FrozenContract):
    """Construction/legality evidence, never execution or live_verified evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["iag.native_command_validation.v2"]
    command_name: str
    class_name: str
    build_id: str
    status: Literal[
        "native_valid",
        "native_invalid",
        "structure_failed",
        "call_exception",
        "missing_parameters",
        "not_tested",
    ]
    reason: str
    country_id: int | None = Field(ge=0, le=0xFFFFFFFF)
    world_identity: int = Field(default=0, ge=0)
    candidate_index: int = Field(ge=0, le=15)
    candidate_count: int = Field(ge=0, le=16)
    candidate_scan_truncated: bool
    scoped_lookup_calls: int = Field(default=0, ge=0, le=256)
    candidate_source: Literal["legacy_bounded", "native_domain", "constraint_plan"] = "legacy_bounded"
    parameter_source: str = Field(default="legacy_independent_pools", max_length=96)
    candidate_identity: str = Field(default="", max_length=1024)
    domain_query_calls: int = Field(default=0, ge=0, le=64)
    native_rule_valid: bool | None = None
    structure_checked: bool
    constructed_from_generated_metadata: bool
    native_is_valid: bool | None
    native_reason: str = Field(default="", max_length=4096)
    validator_kind: Literal["native_predicate", "context_free_constant", "unknown"] = (
        "unknown"
    )
    parameters_populated: bool | None = None
    factory_rva: int = Field(ge=0)
    vtable_rva: int = Field(ge=0)
    object_size: int = Field(ge=0, le=1024 * 1024)
    submitted: Literal[False]
    execution_verified: Literal[False]
    destroyed: bool
    run_game_update: bool
    fixture_paused: bool | None = None
    game_date_before: int | None = Field(default=None, ge=0)
    game_date_after: int | None = Field(default=None, ge=0)
    elapsed_us: int = Field(ge=0)
    create_us: int = Field(ge=0)
    populate_us: int = Field(ge=0)
    validate_us: int = Field(ge=0)
    destroy_us: int = Field(ge=0)
    bindings: tuple[NativeProbeBinding, ...]

    @model_validator(mode="after")
    def check_evidence(self) -> NativeCommandValidation:
        if (
            self.parameters_populated is True
            and not self.constructed_from_generated_metadata
        ):
            raise ValueError("Population claimed without native construction.")
        if (
            self.constructed_from_generated_metadata
            and not self.destroyed
            and self.status != "call_exception"
        ):
            raise ValueError("Incomplete native object destruction evidence.")
        if self.status in {"native_valid", "native_invalid"}:
            if self.candidate_source in {"native_domain", "constraint_plan"} and not self.candidate_identity:
                raise ValueError(
                    "Native domain validation lacks correlated input identity."
                )
            if not (
                self.structure_checked
                and self.constructed_from_generated_metadata
                and self.destroyed
                and self.native_is_valid is (self.status == "native_valid")
                and self.parameters_populated is not False
            ):
                raise ValueError("Incomplete native validation lifecycle evidence.")
        elif self.native_is_valid is not None:
            raise ValueError("Non-validation result claims native legality.")
        return self


class NativeOpenEvent(FrozenContract):
    """Stable, non-RNG-mutating view of one event awaiting a response."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    open_event_id: int = Field(ge=0, le=0xFFFFFFFF)
    event_definition_id: int = Field(ge=0, le=0xFFFFFFFF)
    title_key: str = Field(max_length=512)
    description_state: Literal["dynamic_unrendered"]
    options_truncated: bool
    options: tuple[NativeOpenEventOption, ...]


class NativeOpenEventState(FrozenContract):
    """Read-only event candidates for one country from the current game state."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["iag.open_event_state.v1"]
    country_id: int = Field(ge=0, le=0xFFFFFFFF)
    content_mode: Literal["stable_keys_no_rng"]
    truncated: bool
    events: tuple[NativeOpenEvent, ...]


class NativePendingDiplomaticAction(FrozenContract):
    """One currently pending diplomatic action and its legal responses."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    pending_action_id: int = Field(ge=1, le=0xFFFFFFFFFFFFFFFF)
    action_tag: str = Field(min_length=1, max_length=512)
    actor_country_id: int = Field(ge=0, le=0xFFFFFFFF)
    recipient_country_id: int = Field(ge=0, le=0xFFFFFFFF)
    can_accept: bool
    can_reject: bool


class NativePendingDiplomaticActionState(FrozenContract):
    """Read-only response candidates for one country's diplomatic inbox."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["iag.pending_diplomatic_action_state.v1"]
    country_id: int = Field(ge=0, le=0xFFFFFFFF)
    truncated: bool
    actions: tuple[NativePendingDiplomaticAction, ...]


def _require_token(value: str, *, maximum: int, label: str) -> str:
    if not value or len(value) > maximum or _TOKEN_RE.fullmatch(value) is None:
        raise NativeRuntimeError(f"Invalid {label} for native runtime protocol.")
    return value


class NativeRuntimeClient:
    """Synchronous client for a Unix socket or Windows named pipe runtime."""

    def __init__(
        self,
        endpoint: str | os.PathLike[str] | None = None,
        *,
        timeout_seconds: float = 20.0,
        loader_path: str | os.PathLike[str] | None = None,
        library_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self.endpoint = str(
            endpoint
            if endpoint is not None
            else (
                DEFAULT_NATIVE_RUNTIME_PIPE
                if os.name == "nt"
                else DEFAULT_NATIVE_RUNTIME_SOCKET
            )
        )
        self.socket_path = Path(self.endpoint)
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 60.0))
        native_root = project_root() / "native_runtime"
        self.loader_path = Path(
            loader_path or native_root / "iag_stellaris_native_runtime_loader.exe"
        )
        self.library_path = Path(
            library_path or native_root / "iag_stellaris_native_runtime.dll"
        )
        self._manifest: NativeRuntimeManifest | None = None
        self._manifest_lock = threading.Lock()

    def available(self) -> bool:
        if os.name == "posix":
            try:
                return stat.S_ISSOCK(Path(self.endpoint).stat().st_mode)
            except OSError:
                return False
        if os.name == "nt":
            try:
                import ctypes

                if ctypes.windll.kernel32.WaitNamedPipeW(self.endpoint, 0):
                    return True
                # A busy single-instance pipe is already a loaded runtime, not
                # a reason to inject the DLL again.
                return int(ctypes.windll.kernel32.GetLastError()) in {121, 231}
            except (AttributeError, OSError):
                return False
        return False

    def ensure_available(self) -> bool:
        """Load the exact-build Windows runtime once when explicitly enabled."""

        if self.available():
            return True
        if os.name != "nt":
            return False
        if not self.loader_path.is_file() or not self.library_path.is_file():
            return False
        creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            completed = subprocess.run(
                (str(self.loader_path), str(self.library_path)),
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
                creationflags=creation_flags,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if completed.returncode != 0:
            return False
        deadline = time.monotonic() + min(self.timeout_seconds, 10.0)
        while time.monotonic() < deadline:
            if self.available():
                return True
            time.sleep(0.1)
        return False

    @staticmethod
    def _receive_line(connection: socket.socket) -> str:
        payload = bytearray()
        while len(payload) <= _MAX_RESPONSE_BYTES:
            chunk = connection.recv(4096)
            if not chunk:
                break
            payload.extend(chunk)
            newline = payload.find(b"\n")
            if newline >= 0:
                del payload[newline + 1 :]
                break
        return NativeRuntimeClient._decode_line(bytes(payload))

    @staticmethod
    def _decode_line(payload: bytes) -> str:
        if not payload.endswith(b"\n"):
            raise NativeRuntimeError("Native runtime returned an incomplete response.")
        if len(payload) > _MAX_RESPONSE_BYTES:
            raise NativeRuntimeError("Native runtime response exceeded its size limit.")
        try:
            return payload[:-1].decode("utf-8")
        except UnicodeDecodeError as error:
            raise NativeRuntimeError(
                "Native runtime response was not valid UTF-8."
            ) from error

    def _exchange(self, request: bytes) -> str:
        if os.name == "posix":
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                    connection.settimeout(self.timeout_seconds)
                    connection.connect(self.endpoint)
                    connection.sendall(request)
                    return self._receive_line(connection)
            except OSError as error:
                raise NativeRuntimeError(
                    f"Native runtime request failed: {error}"
                ) from error
        if os.name == "nt":
            try:
                with open(self.endpoint, "r+b", buffering=0) as pipe:
                    pipe.write(request)
                    payload = bytearray()
                    while len(payload) <= _MAX_RESPONSE_BYTES:
                        chunk = pipe.read(4096)
                        if not chunk:
                            break
                        payload.extend(chunk)
                        if b"\n" in chunk:
                            break
                return self._decode_line(bytes(payload))
            except OSError as error:
                raise NativeRuntimeError(
                    f"Native runtime request failed: {error}"
                ) from error
        raise NativeRuntimeError("Native runtime transport is unsupported.")

    @staticmethod
    def _parse_response(
        line: str,
        *,
        request_id: str,
        action: str,
        country_id: int,
        target_echo: str | None = None,
    ) -> NativeRuntimeResponse:
        fields = line.split("\t")
        if len(fields) != 8 or fields[0] != _PROTOCOL_VERSION:
            raise NativeRuntimeError("Native runtime returned an invalid response.")
        if fields[1] != request_id or fields[2] != action:
            raise NativeRuntimeError("Native runtime response correlation failed.")
        try:
            response_country_id = int(fields[5], 10)
        except ValueError as error:
            raise NativeRuntimeError(
                "Native runtime returned an invalid country id."
            ) from error
        response = NativeRuntimeResponse(
            request_id=fields[1],
            action=fields[2],
            outcome=NativeRuntimeOutcome(fields[3]),
            build_id=fields[4],
            country_id=response_country_id,
            target_echo=fields[6],
            detail=fields[7],
        )
        if response.build_id not in SUPPORTED_NATIVE_RUNTIME_BUILD_IDS:
            raise NativeRuntimeError("Native runtime build identity is unsupported.")
        if response.outcome not in {
            NativeRuntimeOutcome.REJECTED,
            NativeRuntimeOutcome.FAILED,
            NativeRuntimeOutcome.CONFLICT,
            NativeRuntimeOutcome.BUSY,
        }:
            if response.country_id != country_id:
                raise NativeRuntimeError(
                    "Native runtime echoed a different country id."
                )
            if target_echo is not None and response.target_echo != target_echo:
                raise NativeRuntimeError("Native runtime echoed a different target.")
        return response

    def _request(
        self,
        *,
        request_id: str,
        action: str,
        country_id: int,
        target_fields: tuple[str, ...],
        target_echo: str | None = None,
    ) -> NativeRuntimeResponse:
        request = (
            "\t".join(
                (_PROTOCOL_VERSION, request_id, action, str(country_id), *target_fields)
            ).encode("ascii")
            + b"\n"
        )
        return self._parse_response(
            self._exchange(request),
            request_id=request_id,
            action=action,
            country_id=country_id,
            target_echo=target_echo,
        )

    def describe_tools(self, *, refresh: bool = False) -> NativeRuntimeManifest:
        """Return the runtime-owned catalog, cached for one backend lifetime."""

        with self._manifest_lock:
            if self._manifest is not None and not refresh:
                return self._manifest
            request_id = "runtime-tool-manifest"
            request = (
                f"{_PROTOCOL_VERSION}\t{request_id}\t{_DESCRIBE_ACTION}\t0\n"
            ).encode("ascii")
            response = self._parse_response(
                self._exchange(request),
                request_id=request_id,
                action=_DESCRIBE_ACTION,
                country_id=0,
            )
            if response.outcome != NativeRuntimeOutcome.CONFIRMED:
                raise NativeRuntimeError(
                    f"Runtime tool manifest failed: {response.detail}"
                )
            try:
                manifest = NativeRuntimeManifest.model_validate_json(
                    response.target_echo
                )
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                raise NativeRuntimeError(
                    "Native runtime returned an invalid tool manifest."
                ) from error
            if manifest.build_id != response.build_id:
                raise NativeRuntimeError("Runtime manifest build identity changed.")
            self._manifest = manifest
            return manifest

    def inspect_open_events(
        self,
        *,
        request_id: str,
        country_id: int,
    ) -> NativeOpenEventState:
        """Read stable event/option keys without evaluating dynamic game text."""

        request_id = _require_token(str(request_id), maximum=96, label="request id")
        if country_id < 0 or country_id > 0xFFFFFFFF:
            raise NativeRuntimeError("Invalid country id for native runtime protocol.")
        response = self._request(
            request_id=request_id,
            action=_INSPECT_OPEN_EVENTS_ACTION,
            country_id=country_id,
            target_fields=(),
        )
        if response.outcome != NativeRuntimeOutcome.CONFIRMED:
            raise NativeRuntimeError(
                f"Open-event state query failed: {response.detail}"
            )
        try:
            state = NativeOpenEventState.model_validate_json(response.target_echo)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise NativeRuntimeError(
                "Native runtime returned invalid open-event state."
            ) from error
        if state.country_id != country_id:
            raise NativeRuntimeError(
                "Native open-event state belongs to a different country."
            )
        return state

    def describe_recovered_commands(
        self, *, request_id: str
    ) -> NativeRecoveredCommandCatalog:
        request_id = _require_token(request_id, maximum=96, label="request id")
        response = self._request(
            request_id=request_id,
            action="describe_recovered_commands",
            country_id=0,
            target_fields=(),
        )
        if response.outcome != NativeRuntimeOutcome.CONFIRMED:
            raise NativeRuntimeError(
                f"Recovered catalog query failed: {response.detail}"
            )
        try:
            catalog = NativeRecoveredCommandCatalog.model_validate_json(
                response.target_echo
            )
        except (ValueError, TypeError) as error:
            raise NativeRuntimeError("Invalid recovered command catalog.") from error
        if catalog.build_id != response.build_id:
            raise NativeRuntimeError("Recovered catalog build identity changed.")
        return catalog

    def validate_recovered_command(
        self,
        *,
        request_id: str,
        command_name: str,
        country_id: int | None = None,
        leader_id: int | None = None,
        candidate_index: int = 0,
        candidate_source: Literal["legacy_bounded", "native_domain"] = "legacy_bounded",
    ) -> NativeCommandValidation:
        """One automatically selected, typed candidate on the existing game-thread lane.

        No loader, submission, execution, raw pointer or arbitrary field write is
        exposed. Numeric/enum semantics and unresolved object types are skipped.
        """
        request_id = _require_token(request_id, maximum=96, label="request id")
        command_name = _require_token(command_name, maximum=96, label="command name")
        for value in (country_id, leader_id):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value < 0xFFFFFFFF
            ):
                raise NativeRuntimeError("Invalid research probe object id.")
        if type(candidate_index) is not int or not 0 <= candidate_index < 16:
            raise NativeRuntimeError("Invalid research candidate index.")
        if candidate_source not in {"legacy_bounded", "native_domain"} or (
            candidate_source == "native_domain" and leader_id is not None
        ):
            raise NativeRuntimeError("Invalid correlated candidate source or override.")
        response = self._request(
            request_id=request_id,
            action="validate_recovered_command",
            country_id=0xFFFFFFFF if country_id is None else country_id,
            target_fields=(
                command_name,
                "auto" if leader_id is None else str(leader_id),
                str(candidate_index),
            )
            + (("native_domain",) if candidate_source == "native_domain" else ()),
        )
        if response.outcome != NativeRuntimeOutcome.CONFIRMED:
            raise NativeRuntimeError(
                f"Generated command validation failed: {response.detail}"
            )
        try:
            result = NativeCommandValidation.model_validate_json(response.target_echo)
        except (ValueError, TypeError) as error:
            raise NativeRuntimeError(
                "Invalid generated command validation result."
            ) from error
        if (
            result.command_name != command_name
            or result.build_id != response.build_id
            or result.candidate_index != candidate_index
            or result.candidate_source != candidate_source
            or (country_id is not None and result.country_id not in (country_id, None))
        ):
            raise NativeRuntimeError("Generated command validation target mismatch.")
        if leader_id is not None and result.constructed_from_generated_metadata:
            selected = [b for b in result.bindings if b.reference_type == "CLeader"]
            if not selected or any(b.value != leader_id for b in selected):
                raise NativeRuntimeError(
                    "Generated command validation target mismatch."
                )
        return result

    def validate_constraint_candidate(
        self,
        *,
        request_id: str,
        command_name: str,
        catalog: NativeRecoveredCommandCatalog,
        expected_world: int,
        expected_date: int,
        candidate_identity: str,
        bindings: tuple[NativeProbeBinding, ...],
        country_id: int | None = None,
    ) -> NativeCommandValidation:
        """Private research lane: generated typed bindings, never submission.

        Does not attach/inject, reload, or unpause. The active SDK rechecks every
        field, enum domain, generation-bearing ref and lifecycle on CGameIdler.
        A matching date/world does not prove complete save-state equivalence.
        """
        _require_token(request_id, maximum=96, label="request id")
        _require_token(command_name, maximum=96, label="command name")
        if (
            catalog.probe_revision < 6
            or command_name not in catalog.commands
            or not re.fullmatch(r"[0-9a-f]{64}", catalog.sdk_fingerprint)
            or not re.fullmatch(r"[0-9a-f]{64}", candidate_identity)
            or type(expected_world) is not int or not 0 < expected_world <= 0xFFFFFFFFFFFFFFFF
            or type(expected_date) is not int or not 0 <= expected_date <= 0xFFFFFFFF
            or (country_id is not None and (type(country_id) is not int or not 0 <= country_id < 0xFFFFFFFF))
            or not 1 <= len(bindings) <= 32
            or len({b.field for b in bindings}) != len(bindings)
        ):
            raise NativeRuntimeError("Invalid or unsupported constraint-plan context.")
        encoded = []
        for binding in bindings:
            _require_token(binding.field, maximum=96, label="recovered field")
            kind = binding.storage_kind
            if kind not in {"ref", "i32", "i64", "u32", "bool", "definition_pointer"} or binding.reference_ids:
                raise NativeRuntimeError("Unsupported constraint-plan field kind.")
            if kind == "i64" and catalog.probe_revision < 7:
                raise NativeRuntimeError("Signed i64 constraint bindings require probe revision 7.")
            if kind == "definition_pointer":
                value = _require_token(binding.text_value, maximum=128, label="definition key")
            else:
                if binding.text_value or (kind == "ref" and binding.value == 0xFFFFFFFF) or (kind == "bool" and binding.value > 1):
                    raise NativeRuntimeError("Invalid constraint-plan field value.")
                value = str(binding.value - 0x100000000 if kind == "i32" and binding.value > 0x7FFFFFFF else binding.value)
            encoded.append(f"{binding.field}~{kind}~{value}")
        document = "|".join(encoded)
        if len(document) > 8192:
            raise NativeRuntimeError("Constraint-plan binding document exceeds limit.")
        response = self._request(
            request_id=request_id, action="validate_recovered_command",
            country_id=0xFFFFFFFF if country_id is None else country_id,
            target_fields=(command_name, "auto", "0", "constraint_plan", str(expected_world), str(expected_date),
                           candidate_identity, catalog.sdk_fingerprint, document, str(catalog.instance_id)),
        )
        if response.outcome != NativeRuntimeOutcome.CONFIRMED:
            raise NativeRuntimeError(f"Constraint-plan validation failed: {response.detail}")
        try:
            result = NativeCommandValidation.model_validate_json(response.target_echo)
        except (ValueError, TypeError) as error:
            raise NativeRuntimeError("Invalid constraint-plan validation result.") from error
        if (response.build_id != catalog.build_id or result.build_id != catalog.build_id
                or result.command_name != command_name or result.candidate_source != "constraint_plan"
                or result.candidate_identity != candidate_identity):
            raise NativeRuntimeError("Constraint-plan identity changed.")
        if result.native_is_valid is not None:
            if (result.world_identity != expected_world or result.game_date_before != expected_date
                    or result.game_date_after != expected_date or result.fixture_paused is not True
                    or result.bindings != bindings):
                raise NativeRuntimeError("Constraint-plan state or populated bindings changed.")
        return result

    def probe_hire_leader(
        self, *, request_id: str, country_id: int, leader_id: int
    ) -> NativeCommandValidation:
        return self.validate_recovered_command(
            request_id=request_id,
            command_name="hire_leader",
            country_id=country_id,
            leader_id=leader_id,
        )

    def inspect_pending_diplomatic_actions(
        self,
        *,
        request_id: str,
        country_id: int,
    ) -> NativePendingDiplomaticActionState:
        """Read pending diplomacy IDs and responses without changing game state."""

        request_id = _require_token(str(request_id), maximum=96, label="request id")
        if country_id < 0 or country_id > 0xFFFFFFFF:
            raise NativeRuntimeError("Invalid country id for native runtime protocol.")
        response = self._request(
            request_id=request_id,
            action=_INSPECT_PENDING_DIPLOMATIC_ACTIONS_ACTION,
            country_id=country_id,
            target_fields=(),
        )
        if response.outcome != NativeRuntimeOutcome.CONFIRMED:
            raise NativeRuntimeError(
                f"Pending-diplomacy state query failed: {response.detail}"
            )
        try:
            state = NativePendingDiplomaticActionState.model_validate_json(
                response.target_echo
            )
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise NativeRuntimeError(
                "Native runtime returned invalid pending-diplomacy state."
            ) from error
        if state.country_id != country_id:
            raise NativeRuntimeError(
                "Native pending-diplomacy state belongs to a different country."
            )
        return state

    def execute(
        self,
        *,
        request_id: str,
        action_type: str,
        action_version: int,
        country_id: int,
        target: Mapping[str, Any],
    ) -> NativeRuntimeResponse:
        """Encode one reviewed semantic target using runtime-declared ordering."""

        request_id = _require_token(str(request_id), maximum=96, label="request id")
        action_type = _require_token(str(action_type), maximum=64, label="action type")
        if country_id < 0 or country_id > 0xFFFFFFFF:
            raise NativeRuntimeError("Invalid country id for native runtime protocol.")
        try:
            tool = self.describe_tools().get(action_type, action_version)
        except KeyError as error:
            raise NativeRuntimeError(str(error)) from error
        fields: list[str] = []
        for parameter in tool.parameters:
            value = target.get(parameter.name)
            if parameter.name not in target or value is None:
                if parameter.required:
                    raise NativeRuntimeError(
                        f"Missing runtime parameter {parameter.name!r}."
                    )
                fields.append("")
                continue
            fields.append(parameter.encode(value))
        return self._request(
            request_id=request_id,
            action=action_type,
            country_id=country_id,
            target_fields=tuple(fields),
        )

    # Compatibility wrappers remain private to the backend migration. New
    # action implementations use execute() and need no Python dispatch branch.
    def stop_research(
        self,
        *,
        request_id: str,
        country_id: int,
        technology_id: str,
    ) -> NativeRuntimeResponse:
        if (
            not technology_id
            or len(technology_id) > 160
            or _TECHNOLOGY_RE.fullmatch(technology_id) is None
        ):
            raise NativeRuntimeError(
                "Invalid technology id for native runtime protocol."
            )
        return self.execute(
            request_id=request_id,
            action_type="stop_research",
            action_version=1,
            country_id=country_id,
            target={"technology_id": technology_id},
        )

    def move_fleet(
        self,
        *,
        request_id: str,
        country_id: int,
        fleet_id: int,
        destination_system_id: int,
    ) -> NativeRuntimeResponse:
        return self.execute(
            request_id=request_id,
            action_type="move_fleet",
            action_version=1,
            country_id=country_id,
            target={
                "fleet_id": fleet_id,
                "destination_system_id": destination_system_id,
            },
        )

    def attack_fleet(
        self,
        *,
        request_id: str,
        country_id: int,
        fleet_id: int,
        target_fleet_id: int,
    ) -> NativeRuntimeResponse:
        return self.execute(
            request_id=request_id,
            action_type="attack_fleet",
            action_version=1,
            country_id=country_id,
            target={"fleet_id": fleet_id, "target_fleet_id": target_fleet_id},
        )
