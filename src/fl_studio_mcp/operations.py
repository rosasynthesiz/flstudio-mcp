"""Internal operation registry for safe FL Studio command orchestration.

The registry is deliberately not an MCP tool surface. It describes existing
safe primitives so later domain tools and batch execution can validate and
prepare operations before any FL Studio mutation occurs.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from . import protocol

SafetyClass = str
BatchCategory = str


class OperationValidationError(ValueError):
    """Raised when an operation id or operation parameters are invalid."""


@dataclass(frozen=True)
class OperationCommand:
    """A protocol command and its validated payload."""

    command: str
    params: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"command": self.command, "params": dict(self.params)}


@dataclass(frozen=True)
class PreparedOperation:
    """A validated operation ready to be passed to the safety layer."""

    spec: OperationSpec
    params: dict[str, Any]
    command: OperationCommand
    snapshot_scope: str | None
    readback_scope: str | None
    verify: tuple[str, Any] | None = None

    @property
    def domain(self) -> str:
        return self.spec.domain

    @property
    def action(self) -> str:
        return self.spec.action

    @property
    def safety_class(self) -> SafetyClass:
        return self.spec.safety_class

    @property
    def batch_eligible(self) -> bool:
        return self.spec.batch_eligible

    @property
    def batch_category(self) -> BatchCategory:
        return self.spec.batch_category

    def build_restore(self, before: Mapping[str, Any]) -> dict[str, Any]:
        if self.spec.restore_builder is None:
            raise OperationValidationError(
                f"operation {self.domain}.{self.action} has no restore builder"
            )
        return self.spec.restore_builder(self.params, before).as_dict()

    def safe_write_kwargs(self, *, tool: str | None = None) -> dict[str, Any]:
        if self.snapshot_scope is None:
            raise OperationValidationError(
                f"operation {self.domain}.{self.action} has no snapshot scope"
            )
        out = {
            "tool": tool or f"{self.domain}_{self.action}",
            "scope": self.snapshot_scope,
            "command": self.command.command,
            "params": dict(self.command.params),
            "build_restore": self.build_restore,
        }
        if self.verify is not None:
            out["verify"] = self.verify
        return out

    def safe_write_group_entry(self) -> dict[str, Any]:
        if self.snapshot_scope is None:
            raise OperationValidationError(
                f"operation {self.domain}.{self.action} has no snapshot scope"
            )
        return {
            "snap_scope": self.snapshot_scope,
            "read_scope": self.readback_scope or self.snapshot_scope,
            "command": self.command.command,
            "params": dict(self.command.params),
            "restore": self.build_restore,
            "verify": self.verify,
        }


@dataclass(frozen=True)
class OperationSpec:
    """Declarative description of one internal FL Studio operation."""

    domain: str
    action: str
    safety_class: SafetyClass
    validator: Callable[[Mapping[str, Any]], dict[str, Any]]
    command_builder: Callable[[Mapping[str, Any]], OperationCommand]
    snapshot_scope_builder: Callable[[Mapping[str, Any]], str] | None = None
    restore_builder: Callable[[Mapping[str, Any], Mapping[str, Any]], OperationCommand] | None = (
        None
    )
    readback_scope_builder: Callable[[Mapping[str, Any]], str] | None = None
    verify_builder: Callable[[Mapping[str, Any]], tuple[str, Any] | None] | None = None
    batch_eligible: bool = False
    batch_category: BatchCategory = "excluded"

    @property
    def key(self) -> tuple[str, str]:
        return (self.domain, self.action)

    def prepare(self, params: Mapping[str, Any]) -> PreparedOperation:
        validated = self.validator(params)
        snapshot_scope = (
            self.snapshot_scope_builder(validated) if self.snapshot_scope_builder else None
        )
        readback_scope = (
            self.readback_scope_builder(validated)
            if self.readback_scope_builder
            else snapshot_scope
        )
        verify = self.verify_builder(validated) if self.verify_builder else None
        return PreparedOperation(
            spec=self,
            params=validated,
            command=self.command_builder(validated),
            snapshot_scope=snapshot_scope,
            readback_scope=readback_scope,
            verify=verify,
        )


class OperationRegistry:
    """Lookup and validation container for operation specs."""

    def __init__(self, specs: Iterable[OperationSpec]) -> None:
        self._specs: dict[tuple[str, str], OperationSpec] = {}
        for spec in specs:
            if spec.key in self._specs:
                raise OperationValidationError(f"duplicate operation: {spec.domain}.{spec.action}")
            self._specs[spec.key] = spec

    def get(self, domain: str, action: str) -> OperationSpec:
        try:
            return self._specs[(domain, action)]
        except KeyError as exc:
            raise OperationValidationError(f"unknown operation: {domain}.{action}") from exc

    def prepare(self, domain: str, action: str, params: Mapping[str, Any]) -> PreparedOperation:
        return self.get(domain, action).prepare(params)

    def list_specs(self) -> list[OperationSpec]:
        return [self._specs[key] for key in sorted(self._specs)]


def _reject_unknown(params: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = set(params) - allowed
    if unknown:
        names = ", ".join(sorted(unknown))
        raise OperationValidationError(f"unknown parameter(s): {names}")


def _non_bool_int(params: Mapping[str, Any], name: str, *, minimum: int = 0) -> int:
    if name not in params:
        raise OperationValidationError(f"missing parameter: {name}")
    value = params[name]
    if type(value) is not int or value < minimum:
        raise OperationValidationError(f"{name} must be an integer >= {minimum}")
    return value


def _finite_number(params: Mapping[str, Any], name: str) -> float:
    if name not in params:
        raise OperationValidationError(f"missing parameter: {name}")
    value = params[name]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise OperationValidationError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise OperationValidationError(f"{name} must be a finite number")
    return value


def _string_param(params: Mapping[str, Any], name: str, *, min_length: int = 0) -> str:
    if name not in params:
        raise OperationValidationError(f"missing parameter: {name}")
    value = params[name]
    if not isinstance(value, str) or len(value) < min_length:
        raise OperationValidationError(f"{name} must be a string")
    return value


def _bool_param(params: Mapping[str, Any], name: str) -> bool:
    if name not in params:
        raise OperationValidationError(f"missing parameter: {name}")
    value = params[name]
    if type(value) is not bool:
        raise OperationValidationError(f"{name} must be a boolean")
    return value


def _optional_page_start(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"start"})
    if "start" not in params:
        return {}
    return {"start": _non_bool_int(params, "start")}


def _validate_empty(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, set())
    return {}


def _validate_mixer_volume(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"track", "value", "unit"})
    track = _non_bool_int(params, "track")
    value = _finite_number(params, "value")
    unit = params.get("unit", "normalized")
    if not isinstance(unit, str) or unit not in {"normalized", "db"}:
        raise OperationValidationError("unit must be 'normalized' or 'db'")
    if unit == "normalized" and not 0.0 <= value <= 1.0:
        raise OperationValidationError("normalized mixer volume must be 0..1")
    return {"track": track, "value": value, "unit": unit}


def _validate_track_value(params: Mapping[str, Any], *, value_name: str) -> dict[str, Any]:
    _reject_unknown(params, {"track", value_name})
    return {
        "track": _non_bool_int(params, "track"),
        value_name: _finite_number(params, value_name),
    }


def _validate_mixer_pan(params: Mapping[str, Any]) -> dict[str, Any]:
    out = _validate_track_value(params, value_name="value")
    if not -1.0 <= out["value"] <= 1.0:
        raise OperationValidationError("mixer pan value must be -1..1")
    return out


def _validate_mixer_stereo_sep(params: Mapping[str, Any]) -> dict[str, Any]:
    return _validate_mixer_pan(params)


def _validate_mixer_track_read(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"track"})
    return {"index": _non_bool_int(params, "track")}


def _validate_mixer_track_param(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"track"})
    return {"track": _non_bool_int(params, "track")}


def _validate_mixer_name(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"track", "name"})
    return {"track": _non_bool_int(params, "track"), "name": _string_param(params, "name")}


def _validate_track_bool(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"track", "state"})
    return {"track": _non_bool_int(params, "track"), "state": _bool_param(params, "state")}


def _validate_color_params(
    params: Mapping[str, Any], *, index_name: str, output_name: str
) -> dict[str, Any]:
    has_int = "color" in params and params["color"] is not None
    has_rgb = any(k in params for k in ("r", "g", "b"))
    if has_int and has_rgb:
        raise OperationValidationError("use either color or r/g/b, not both")
    allowed = {index_name, "color"} if has_int else {index_name, "r", "g", "b"}
    _reject_unknown(params, allowed)
    out = {output_name: _non_bool_int(params, index_name)}
    if has_int:
        color = _non_bool_int(params, "color")
        if color > 0xFFFFFF:
            raise OperationValidationError("color must be 0..16777215")
        out["color"] = color
        return out
    missing = {"r", "g", "b"} - set(params)
    if missing:
        names = ", ".join(sorted(missing))
        raise OperationValidationError(f"missing RGB parameter(s): {names}")
    for name in ("r", "g", "b"):
        value = _non_bool_int(params, name)
        if value > 255:
            raise OperationValidationError(f"{name} must be 0..255")
        out[name] = value
    return out


def _validate_mixer_color(params: Mapping[str, Any]) -> dict[str, Any]:
    return _validate_color_params(params, index_name="track", output_name="track")


def _validate_mixer_route(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"src", "dst", "enabled"})
    return {
        "src": _non_bool_int(params, "src"),
        "dst": _non_bool_int(params, "dst"),
        "enabled": _bool_param(params, "enabled"),
    }


def _validate_channel_name(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"channel", "name"})
    return {
        "channel": _non_bool_int(params, "channel"),
        "name": _string_param(params, "name", min_length=1),
    }


def _validate_channel_target(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"channel", "track"})
    return {
        "channel": _non_bool_int(params, "channel"),
        "track": _non_bool_int(params, "track"),
    }


def _validate_channel_read(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"channel"})
    return {"index": _non_bool_int(params, "channel")}


def _validate_channel_param(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"channel"})
    return {"channel": _non_bool_int(params, "channel")}


def _validate_channel_color(params: Mapping[str, Any]) -> dict[str, Any]:
    return _validate_color_params(params, index_name="channel", output_name="channel")


def _validate_channel_volume(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"channel", "value", "unit"})
    channel = _non_bool_int(params, "channel")
    value = _finite_number(params, "value")
    unit = params.get("unit", "normalized")
    if not isinstance(unit, str) or unit not in {"normalized", "db"}:
        raise OperationValidationError("unit must be 'normalized' or 'db'")
    if unit == "normalized" and not 0.0 <= value <= 1.0:
        raise OperationValidationError("normalized channel volume must be 0..1")
    return {"channel": channel, "value": value, "unit": unit}


def _validate_channel_pan(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"channel", "value"})
    out = {"channel": _non_bool_int(params, "channel"), "value": _finite_number(params, "value")}
    if not -1.0 <= out["value"] <= 1.0:
        raise OperationValidationError("channel pan value must be -1..1")
    return out


def _validate_channel_bool(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"channel", "state"})
    return {"channel": _non_bool_int(params, "channel"), "state": _bool_param(params, "state")}


def _validate_tempo(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"bpm"})
    bpm = _finite_number(params, "bpm")
    if not 10.0 <= bpm <= 999.0:
        raise OperationValidationError("bpm must be 10..999")
    return {"bpm": bpm}


def _validate_time_signature(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"numerator", "denominator"})
    numerator = _non_bool_int(params, "numerator", minimum=1)
    if numerator > 64:
        raise OperationValidationError("numerator must be 1..64")
    denominator = _non_bool_int(params, "denominator", minimum=1)
    if denominator not in (4, 8):
        raise OperationValidationError("denominator must be 4 or 8")
    return {"numerator": numerator, "denominator": denominator}


def _validate_song_position(params: Mapping[str, Any]) -> dict[str, Any]:
    present = [name for name in ("beats", "ms", "ticks") if name in params]
    if len(present) != 1:
        raise OperationValidationError("provide exactly one of: beats, ms, ticks")
    _reject_unknown(params, {"beats", "ms", "ticks"})
    name = present[0]
    if name == "ticks":
        return {"ticks": _non_bool_int(params, "ticks")}
    value = _finite_number(params, name)
    if value < 0:
        raise OperationValidationError(f"{name} must be >= 0")
    return {name: value}


def _validate_step(params: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(params, Mapping):
        raise OperationValidationError("each step must be a mapping")
    allowed = {"step", "value", "velocity", "pan", "shift", "repeat", "release", "mod", "pitch"}
    _reject_unknown(params, allowed)
    step = _non_bool_int(params, "step")
    if step > 63:
        raise OperationValidationError("step must be 0..63")
    out: dict[str, Any] = {"step": step}
    if "value" in params:
        out["value"] = _bool_param(params, "value")
    for name in ("velocity", "shift", "release", "mod"):
        if name in params and params[name] is not None:
            value = _finite_number(params, name)
            if not 0.0 <= value <= 1.0:
                raise OperationValidationError(f"{name} must be 0..1")
            out[name] = value
    if "pan" in params and params["pan"] is not None:
        pan = _finite_number(params, "pan")
        if not -1.0 <= pan <= 1.0:
            raise OperationValidationError("pan must be -1..1")
        out["pan"] = pan
    if "repeat" in params and params["repeat"] is not None:
        repeat = _non_bool_int(params, "repeat")
        if repeat > 15:
            raise OperationValidationError("repeat must be 0..15")
        out["repeat"] = repeat
    if "pitch" in params and params["pitch"] is not None:
        if type(params["pitch"]) is not int:
            raise OperationValidationError("pitch must be an integer")
        out["pitch"] = params["pitch"]
    return out


def _validate_channel_steps_read(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"channel", "steps", "pattern"})
    out = {"channel": _non_bool_int(params, "channel")}
    if "steps" in params:
        steps = _non_bool_int(params, "steps", minimum=1)
        if steps > 64:
            raise OperationValidationError("steps must be 1..64")
        out["steps"] = steps
    if "pattern" in params and params["pattern"] is not None:
        out["pattern"] = _non_bool_int(params, "pattern", minimum=1)
    return out


def _validate_channel_steps_write(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"channel", "pattern", "steps"})
    channel = _non_bool_int(params, "channel")
    pattern = _non_bool_int(params, "pattern", minimum=1)
    steps = params.get("steps")
    if not isinstance(steps, list):
        raise OperationValidationError("steps must be a list")
    return {
        "channel": channel,
        "pattern": pattern,
        "steps": [_validate_step(step) for step in steps],
    }


def _bounded_int(
    params: Mapping[str, Any],
    name: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    value = _non_bool_int(params, name, minimum=minimum)
    if maximum is not None and value > maximum:
        raise OperationValidationError(f"{name} must be {minimum}..{maximum}")
    return value


def _validate_pattern_param(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"index"})
    return {"index": _bounded_int(params, "index", minimum=1)}


def _validate_pattern_name(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"index", "name"})
    return {
        "index": _bounded_int(params, "index", minimum=1),
        "name": _string_param(params, "name"),
    }


def _validate_pattern_color(params: Mapping[str, Any]) -> dict[str, Any]:
    return _validate_color_params(params, index_name="index", output_name="index")


def _validate_pattern_length(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"index", "beats"})
    beats = _finite_number(params, "beats")
    if beats <= 0.0:
        raise OperationValidationError("beats must be > 0")
    return {"index": _bounded_int(params, "index", minimum=1), "beats": beats}


def _validate_playlist_track_param(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"index"})
    return {"index": _bounded_int(params, "index", minimum=1)}


def _validate_playlist_track_bool(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"index", "state"})
    return {
        "index": _bounded_int(params, "index", minimum=1),
        "state": _bool_param(params, "state"),
    }


def _validate_playlist_track_select(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"index", "state"})
    out: dict[str, Any] = {"index": _bounded_int(params, "index", minimum=1)}
    out["state"] = _bool_param(params, "state") if "state" in params else True
    return out


def _validate_playlist_track_name(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"index", "name"})
    return {
        "index": _bounded_int(params, "index", minimum=1),
        "name": _string_param(params, "name"),
    }


def _validate_playlist_track_color(params: Mapping[str, Any]) -> dict[str, Any]:
    return _validate_color_params(params, index_name="index", output_name="index")


def _validate_effect_slot(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"track", "slot"})
    return {
        "track": _non_bool_int(params, "track"),
        "slot": _bounded_int(params, "slot", maximum=9),
    }


def _validate_effect_slot_mix(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"track", "slot", "mix"})
    mix = _finite_number(params, "mix")
    if not 0.0 <= mix <= 1.0:
        raise OperationValidationError("mix must be 0..1")
    return {
        "track": _non_bool_int(params, "track"),
        "slot": _bounded_int(params, "slot", maximum=9),
        "mix": mix,
    }


def _validate_effect_slot_enabled(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"track", "slot", "enabled"})
    return {
        "track": _non_bool_int(params, "track"),
        "slot": _bounded_int(params, "slot", maximum=9),
        "enabled": _bool_param(params, "enabled"),
    }


def _validate_track_slots_param(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"track"})
    return {"track": _non_bool_int(params, "track")}


def _validate_track_slots_enabled(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"track", "enabled"})
    return {"track": _non_bool_int(params, "track"), "enabled": _bool_param(params, "enabled")}


def _validate_eq_track(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"track"})
    return {"track": _non_bool_int(params, "track")}


def _validate_eq_band(params: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"track", "band", "gain", "frequency", "bandwidth", "type"}
    _reject_unknown(params, allowed)
    out: dict[str, Any] = {
        "track": _non_bool_int(params, "track"),
        "band": _bounded_int(params, "band", maximum=2),
    }
    changed = False
    for name in ("gain", "frequency", "bandwidth"):
        if name in params and params[name] is not None:
            value = _finite_number(params, name)
            if not 0.0 <= value <= 1.0:
                raise OperationValidationError(f"{name} must be 0..1")
            out[name] = value
            changed = True
    if "type" in params and params["type"] is not None:
        if type(params["type"]) is not int or params["type"] < 0:
            raise OperationValidationError("type must be an integer >= 0")
        out["type"] = params["type"]
        changed = True
    if not changed:
        raise OperationValidationError("at least one EQ field is required")
    return out


def _validate_plugin_track(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"track"})
    return {"track": _non_bool_int(params, "track")}


def _validate_plugin_params_read(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"track", "slot", "start"})
    out = {
        "track": _non_bool_int(params, "track"),
        "slot": _bounded_int(params, "slot", maximum=9),
    }
    if "start" in params:
        out["start"] = _non_bool_int(params, "start")
    return out


def _validate_plugin_param_read(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"track", "slot", "param"})
    return {
        "track": _non_bool_int(params, "track"),
        "slot": _bounded_int(params, "slot", maximum=9),
        "param": _non_bool_int(params, "param"),
    }


def _validate_plugin_param_write(params: Mapping[str, Any]) -> dict[str, Any]:
    out = _validate_plugin_param_read(
        {key: params[key] for key in ("track", "slot", "param") if key in params}
    )
    _reject_unknown(params, {"track", "slot", "param", "value"})
    value = _finite_number(params, "value")
    if not 0.0 <= value <= 1.0:
        raise OperationValidationError("value must be 0..1")
    out["value"] = value
    return out


def _mixer_scope(params: Mapping[str, Any]) -> str:
    return f"mixer_track:{params['track']}"


def _route_scope(params: Mapping[str, Any]) -> str:
    return f"route:{params['src']}:{params['dst']}"


def _channel_scope(params: Mapping[str, Any]) -> str:
    return f"channel:{params['channel']}"


def _channel_steps_scope(params: Mapping[str, Any]) -> str:
    return f"channel_steps:{params['channel']}:{params['pattern']}"


def _pattern_scope(params: Mapping[str, Any]) -> str:
    return f"pattern:{params['index']}"


def _playlist_track_scope(params: Mapping[str, Any]) -> str:
    return f"playlist_track:{params['index']}"


def _effect_slot_scope(params: Mapping[str, Any]) -> str:
    return f"effect_slot:{params['track']}:{params['slot']}"


def _track_slots_scope(params: Mapping[str, Any]) -> str:
    return f"track_slots:{params['track']}"


def _eq_scope(params: Mapping[str, Any]) -> str:
    return f"mixer_eq:{params['track']}"


def _plugin_param_scope(params: Mapping[str, Any]) -> str:
    return f"plugin_param:{params['track']}:{params['slot']}:{params['param']}"


def _cmd(command: str, params: Mapping[str, Any]) -> OperationCommand:
    return OperationCommand(command=command, params=dict(params))


def _restore_mixer_volume(params: Mapping[str, Any], before: Mapping[str, Any]) -> OperationCommand:
    return _cmd(
        protocol.CMD_MIXER_SET_VOLUME,
        {"track": params["track"], "value": before["vol_norm"], "unit": "normalized"},
    )


def _restore_mixer_pan(params: Mapping[str, Any], before: Mapping[str, Any]) -> OperationCommand:
    return _cmd(protocol.CMD_MIXER_SET_PAN, {"track": params["track"], "value": before["pan"]})


def _restore_mixer_name(params: Mapping[str, Any], before: Mapping[str, Any]) -> OperationCommand:
    return _cmd(protocol.CMD_MIXER_SET_NAME, {"track": params["track"], "name": before["name"]})


def _restore_mixer_bool(
    command: str, field: str
) -> Callable[[Mapping[str, Any], Mapping[str, Any]], OperationCommand]:
    return lambda params, before: _cmd(command, {"track": params["track"], "state": before[field]})


def _before_color_int(before: Mapping[str, Any]) -> int:
    color = before.get("color")
    if not isinstance(color, Mapping):
        raise OperationValidationError("cannot restore color without color snapshot")
    value = color.get("int")
    if not isinstance(value, int):
        raise OperationValidationError("cannot restore color without color.int")
    return value


def _restore_mixer_color(params: Mapping[str, Any], before: Mapping[str, Any]) -> OperationCommand:
    return _cmd(
        protocol.CMD_MIXER_SET_COLOR,
        {"track": params["track"], "color": _before_color_int(before)},
    )


def _restore_mixer_stereo_sep(
    params: Mapping[str, Any], before: Mapping[str, Any]
) -> OperationCommand:
    return _cmd(
        protocol.CMD_MIXER_SET_STEREO_SEP,
        {"track": params["track"], "value": before["stereo_sep"]},
    )


def _restore_mixer_selection(
    _params: Mapping[str, Any], before: Mapping[str, Any]
) -> OperationCommand:
    return _cmd(protocol.CMD_MIXER_SELECT_TRACK, {"track": before["track"]})


def _restore_mixer_route(params: Mapping[str, Any], before: Mapping[str, Any]) -> OperationCommand:
    return _cmd(
        protocol.CMD_MIXER_SET_ROUTE,
        {"src": params["src"], "dst": params["dst"], "enabled": before["enabled"]},
    )


def _restore_channel_name(params: Mapping[str, Any], before: Mapping[str, Any]) -> OperationCommand:
    return _cmd(
        protocol.CMD_CHANNEL_SET_NAME, {"channel": params["channel"], "name": before["name"]}
    )


def _restore_channel_volume(
    params: Mapping[str, Any], before: Mapping[str, Any]
) -> OperationCommand:
    return _cmd(
        protocol.CMD_CHANNEL_SET_VOLUME,
        {"channel": params["channel"], "value": before["vol_norm"], "unit": "normalized"},
    )


def _restore_channel_pan(params: Mapping[str, Any], before: Mapping[str, Any]) -> OperationCommand:
    return _cmd(
        protocol.CMD_CHANNEL_SET_PAN, {"channel": params["channel"], "value": before["pan"]}
    )


def _restore_channel_bool(
    command: str, field: str
) -> Callable[[Mapping[str, Any], Mapping[str, Any]], OperationCommand]:
    return lambda params, before: _cmd(
        command, {"channel": params["channel"], "state": before[field]}
    )


def _restore_channel_color(
    params: Mapping[str, Any], before: Mapping[str, Any]
) -> OperationCommand:
    return _cmd(
        protocol.CMD_CHANNEL_SET_COLOR,
        {"channel": params["channel"], "color": _before_color_int(before)},
    )


def _restore_channel_target(
    params: Mapping[str, Any], before: Mapping[str, Any]
) -> OperationCommand:
    previous = before.get("target_fx_track")
    if not isinstance(previous, int):
        raise OperationValidationError("cannot restore channel target without target_fx_track")
    return _cmd(
        protocol.CMD_CHANNEL_SET_TARGET,
        {"channel": params["channel"], "track": previous},
    )


def _restore_channel_selection(
    _params: Mapping[str, Any], before: Mapping[str, Any]
) -> OperationCommand:
    return _cmd(protocol.CMD_CHANNEL_SELECT, {"channel": before["selected"]})


def _restore_channel_steps(
    params: Mapping[str, Any], before: Mapping[str, Any]
) -> OperationCommand:
    steps_list = []
    rel = before.get("release", [])
    mod = before.get("mod", [])
    pitch = before.get("pitch", [])
    for step in range(len(before.get("grid", []))):
        row = {
            "step": step,
            "value": before["grid"][step],
            "velocity": before["vel"][step],
            "pan": before["pan"][step],
            "shift": before["shift"][step],
            "repeat": before["rep"][step],
        }
        if step < len(rel) and rel[step] is not None:
            row["release"] = rel[step]
        if step < len(mod) and mod[step] is not None:
            row["mod"] = mod[step]
        if step < len(pitch) and pitch[step] is not None:
            row["pitch"] = pitch[step]
        steps_list.append(row)
    return _cmd(
        protocol.CMD_CHANNEL_SET_STEPS,
        {"channel": params["channel"], "pattern": before.get("pattern"), "steps": steps_list},
    )


def _restore_tempo(_params: Mapping[str, Any], before: Mapping[str, Any]) -> OperationCommand:
    return _cmd(protocol.CMD_SET_TEMPO, {"bpm": before["bpm"]})


def _restore_time_signature(
    _params: Mapping[str, Any], before: Mapping[str, Any]
) -> OperationCommand:
    return _cmd(
        protocol.CMD_SET_TIME_SIG,
        {"numerator": before["numerator"], "denominator": before["denominator"]},
    )


def _restore_pattern_selection(
    _params: Mapping[str, Any], before: Mapping[str, Any]
) -> OperationCommand:
    return _cmd(protocol.CMD_PATTERN_SELECT, {"index": before["selected"]})


def _restore_pattern_name(params: Mapping[str, Any], before: Mapping[str, Any]) -> OperationCommand:
    return _cmd(protocol.CMD_PATTERN_RENAME, {"index": params["index"], "name": before["name"]})


def _restore_pattern_color(
    params: Mapping[str, Any], before: Mapping[str, Any]
) -> OperationCommand:
    return _cmd(
        protocol.CMD_PATTERN_SET_COLOR,
        {"index": params["index"], "color": _before_color_int(before)},
    )


def _restore_pattern_length(
    params: Mapping[str, Any], before: Mapping[str, Any]
) -> OperationCommand:
    return _cmd(
        protocol.CMD_PATTERN_SET_LENGTH,
        {"index": params["index"], "beats": float(before.get("length", 16))},
    )


def _restore_playlist_track_bool(
    command: str, field: str
) -> Callable[[Mapping[str, Any], Mapping[str, Any]], OperationCommand]:
    return lambda params, before: _cmd(command, {"index": params["index"], "state": before[field]})


def _restore_playlist_track_name(
    params: Mapping[str, Any], before: Mapping[str, Any]
) -> OperationCommand:
    return _cmd(
        protocol.CMD_PLAYLIST_SET_NAME,
        {"index": params["index"], "name": before["name"]},
    )


def _restore_playlist_track_color(
    params: Mapping[str, Any], before: Mapping[str, Any]
) -> OperationCommand:
    return _cmd(
        protocol.CMD_PLAYLIST_SET_COLOR,
        {"index": params["index"], "color": _before_color_int(before)},
    )


def _restore_effect_slot_mix(
    params: Mapping[str, Any], before: Mapping[str, Any]
) -> OperationCommand:
    return _cmd(
        protocol.CMD_MIXER_SET_SLOT_MIX,
        {"track": params["track"], "slot": params["slot"], "mix": float(before.get("mix", 0.8))},
    )


def _restore_effect_slot_enabled(
    params: Mapping[str, Any], before: Mapping[str, Any]
) -> OperationCommand:
    return _cmd(
        protocol.CMD_MIXER_SET_SLOT_ENABLED,
        {
            "track": params["track"],
            "slot": params["slot"],
            "enabled": bool(before.get("enabled", True)),
        },
    )


def _restore_track_slots_enabled(
    params: Mapping[str, Any], before: Mapping[str, Any]
) -> OperationCommand:
    return _cmd(
        protocol.CMD_MIXER_SET_TRACK_SLOTS,
        {"track": params["track"], "enabled": bool(before.get("enabled", True))},
    )


def _eq_band_before(before: Mapping[str, Any], band: int) -> Mapping[str, Any]:
    for row in before.get("bands", []):
        if int(row.get("band", -1)) == int(band):
            return row
    return {"band": int(band), "gain": 0.0, "frequency": 0.5, "bandwidth": 1.0, "type": 0}


def _restore_eq_band(params: Mapping[str, Any], before: Mapping[str, Any]) -> OperationCommand:
    row = _eq_band_before(before, int(params["band"]))
    return _cmd(
        protocol.CMD_MIXER_SET_EQ,
        {
            "track": params["track"],
            "band": params["band"],
            "gain": float(row["gain"]),
            "frequency": float(row["frequency"]),
            "bandwidth": float(row["bandwidth"]),
            "type": int(row.get("type", 0)),
        },
    )


def _restore_plugin_param(params: Mapping[str, Any], before: Mapping[str, Any]) -> OperationCommand:
    return _cmd(
        protocol.CMD_PLUGIN_SET_PARAM,
        {
            "track": params["track"],
            "slot": params["slot"],
            "param": params["param"],
            "value": before["v"],
        },
    )


def _read_spec(
    *,
    domain: str,
    action: str,
    validator: Callable[[Mapping[str, Any]], dict[str, Any]],
    command: str,
) -> OperationSpec:
    return OperationSpec(
        domain=domain,
        action=action,
        safety_class="read-only",
        validator=validator,
        command_builder=lambda params: _cmd(command, params),
        batch_eligible=True,
        batch_category="read_only",
    )


def _transient_spec(
    *,
    domain: str,
    action: str,
    validator: Callable[[Mapping[str, Any]], dict[str, Any]],
    command: str,
) -> OperationSpec:
    return OperationSpec(
        domain=domain,
        action=action,
        safety_class="transient",
        validator=validator,
        command_builder=lambda params: _cmd(command, params),
        batch_eligible=False,
        batch_category="transient",
    )


def _persistent_write_spec(
    *,
    domain: str,
    action: str,
    validator: Callable[[Mapping[str, Any]], dict[str, Any]],
    command: str,
    snapshot_scope_builder: Callable[[Mapping[str, Any]], str],
    restore_builder: Callable[[Mapping[str, Any], Mapping[str, Any]], OperationCommand],
    verify_builder: Callable[[Mapping[str, Any]], tuple[str, Any] | None] | None = None,
) -> OperationSpec:
    return OperationSpec(
        domain=domain,
        action=action,
        safety_class="write-safe",
        validator=validator,
        command_builder=lambda params: _cmd(command, params),
        snapshot_scope_builder=snapshot_scope_builder,
        restore_builder=restore_builder,
        readback_scope_builder=snapshot_scope_builder,
        verify_builder=verify_builder,
        batch_eligible=True,
        batch_category="persistent_write",
    )


_DEFAULT_SPECS = (
    _read_spec(
        domain="channel",
        action="get",
        validator=_validate_channel_read,
        command=protocol.CMD_CHANNEL_GET,
    ),
    _read_spec(
        domain="channel",
        action="get_selected",
        validator=_validate_empty,
        command=protocol.CMD_CHANNEL_SELECTED,
    ),
    _read_spec(
        domain="channel",
        action="get_steps",
        validator=_validate_channel_steps_read,
        command=protocol.CMD_CHANNEL_GET_STEPS,
    ),
    _read_spec(
        domain="channel",
        action="list",
        validator=_optional_page_start,
        command=protocol.CMD_CHANNEL_LIST,
    ),
    _persistent_write_spec(
        domain="channel",
        action="select",
        validator=_validate_channel_param,
        command=protocol.CMD_CHANNEL_SELECT,
        snapshot_scope_builder=lambda _params: "selected_channel",
        restore_builder=_restore_channel_selection,
    ),
    _persistent_write_spec(
        domain="channel",
        action="set_color",
        validator=_validate_channel_color,
        command=protocol.CMD_CHANNEL_SET_COLOR,
        snapshot_scope_builder=_channel_scope,
        restore_builder=_restore_channel_color,
    ),
    _persistent_write_spec(
        domain="channel",
        action="set_mute",
        validator=_validate_channel_bool,
        command=protocol.CMD_CHANNEL_SET_MUTE,
        snapshot_scope_builder=_channel_scope,
        restore_builder=_restore_channel_bool(protocol.CMD_CHANNEL_SET_MUTE, "mute"),
        verify_builder=lambda params: ("mute", params["state"]),
    ),
    _persistent_write_spec(
        domain="channel",
        action="set_name",
        validator=_validate_channel_name,
        command=protocol.CMD_CHANNEL_SET_NAME,
        snapshot_scope_builder=_channel_scope,
        restore_builder=_restore_channel_name,
    ),
    _persistent_write_spec(
        domain="channel",
        action="set_pan",
        validator=_validate_channel_pan,
        command=protocol.CMD_CHANNEL_SET_PAN,
        snapshot_scope_builder=_channel_scope,
        restore_builder=_restore_channel_pan,
    ),
    _persistent_write_spec(
        domain="channel",
        action="set_solo",
        validator=_validate_channel_bool,
        command=protocol.CMD_CHANNEL_SET_SOLO,
        snapshot_scope_builder=_channel_scope,
        restore_builder=_restore_channel_bool(protocol.CMD_CHANNEL_SET_SOLO, "solo"),
        verify_builder=lambda params: ("solo", params["state"]),
    ),
    _persistent_write_spec(
        domain="channel",
        action="set_steps",
        validator=_validate_channel_steps_write,
        command=protocol.CMD_CHANNEL_SET_STEPS,
        snapshot_scope_builder=_channel_steps_scope,
        restore_builder=_restore_channel_steps,
    ),
    _persistent_write_spec(
        domain="channel",
        action="set_volume",
        validator=_validate_channel_volume,
        command=protocol.CMD_CHANNEL_SET_VOLUME,
        snapshot_scope_builder=_channel_scope,
        restore_builder=_restore_channel_volume,
    ),
    _persistent_write_spec(
        domain="channel",
        action="set_mixer_target",
        validator=_validate_channel_target,
        command=protocol.CMD_CHANNEL_SET_TARGET,
        snapshot_scope_builder=_channel_scope,
        restore_builder=_restore_channel_target,
        verify_builder=lambda params: ("target_fx_track", params["track"]),
    ),
    _read_spec(
        domain="mixer",
        action="get",
        validator=_validate_mixer_track_read,
        command=protocol.CMD_MIXER_GET_TRACK,
    ),
    _read_spec(
        domain="mixer",
        action="get_route",
        validator=_validate_mixer_track_param,
        command=protocol.CMD_MIXER_GET_ROUTING,
    ),
    _read_spec(
        domain="mixer",
        action="get_selected",
        validator=_validate_empty,
        command=protocol.CMD_MIXER_SELECTED,
    ),
    _read_spec(
        domain="mixer",
        action="list",
        validator=_optional_page_start,
        command=protocol.CMD_MIXER_LIST_TRACKS,
    ),
    _persistent_write_spec(
        domain="mixer",
        action="select",
        validator=_validate_mixer_track_param,
        command=protocol.CMD_MIXER_SELECT_TRACK,
        snapshot_scope_builder=lambda _params: "mixer_selection",
        restore_builder=_restore_mixer_selection,
        verify_builder=lambda params: ("track", params["track"]),
    ),
    _persistent_write_spec(
        domain="mixer",
        action="set_color",
        validator=_validate_mixer_color,
        command=protocol.CMD_MIXER_SET_COLOR,
        snapshot_scope_builder=_mixer_scope,
        restore_builder=_restore_mixer_color,
    ),
    _persistent_write_spec(
        domain="mixer",
        action="set_mute",
        validator=_validate_track_bool,
        command=protocol.CMD_MIXER_SET_MUTE,
        snapshot_scope_builder=_mixer_scope,
        restore_builder=_restore_mixer_bool(protocol.CMD_MIXER_SET_MUTE, "mute"),
        verify_builder=lambda params: ("mute", params["state"]),
    ),
    _persistent_write_spec(
        domain="mixer",
        action="set_name",
        validator=_validate_mixer_name,
        command=protocol.CMD_MIXER_SET_NAME,
        snapshot_scope_builder=_mixer_scope,
        restore_builder=_restore_mixer_name,
    ),
    _persistent_write_spec(
        domain="mixer",
        action="set_pan",
        validator=_validate_mixer_pan,
        command=protocol.CMD_MIXER_SET_PAN,
        snapshot_scope_builder=_mixer_scope,
        restore_builder=_restore_mixer_pan,
    ),
    _persistent_write_spec(
        domain="mixer",
        action="set_route",
        validator=_validate_mixer_route,
        command=protocol.CMD_MIXER_SET_ROUTE,
        snapshot_scope_builder=_route_scope,
        restore_builder=_restore_mixer_route,
        verify_builder=lambda params: ("enabled", params["enabled"]),
    ),
    _persistent_write_spec(
        domain="mixer",
        action="set_solo",
        validator=_validate_track_bool,
        command=protocol.CMD_MIXER_SET_SOLO,
        snapshot_scope_builder=_mixer_scope,
        restore_builder=_restore_mixer_bool(protocol.CMD_MIXER_SET_SOLO, "solo"),
        verify_builder=lambda params: ("solo", params["state"]),
    ),
    _persistent_write_spec(
        domain="mixer",
        action="set_stereo_separation",
        validator=_validate_mixer_stereo_sep,
        command=protocol.CMD_MIXER_SET_STEREO_SEP,
        snapshot_scope_builder=_mixer_scope,
        restore_builder=_restore_mixer_stereo_sep,
    ),
    _persistent_write_spec(
        domain="mixer",
        action="set_volume",
        validator=_validate_mixer_volume,
        command=protocol.CMD_MIXER_SET_VOLUME,
        snapshot_scope_builder=_mixer_scope,
        restore_builder=_restore_mixer_volume,
    ),
    _read_spec(
        domain="pattern",
        action="find_empty",
        validator=_validate_empty,
        command=protocol.CMD_PATTERN_FIND_EMPTY,
    ),
    _read_spec(
        domain="pattern",
        action="get",
        validator=_validate_pattern_param,
        command=protocol.CMD_PATTERN_GET,
    ),
    _read_spec(
        domain="pattern",
        action="get_length",
        validator=_validate_pattern_param,
        command=protocol.CMD_PATTERN_GET_LENGTH,
    ),
    _read_spec(
        domain="pattern",
        action="get_selected",
        validator=_validate_empty,
        command=protocol.CMD_PATTERN_SELECTED,
    ),
    _read_spec(
        domain="pattern",
        action="list",
        validator=_optional_page_start,
        command=protocol.CMD_PATTERN_LIST,
    ),
    _persistent_write_spec(
        domain="pattern",
        action="select",
        validator=_validate_pattern_param,
        command=protocol.CMD_PATTERN_SELECT,
        snapshot_scope_builder=lambda _params: "patterns_selected",
        restore_builder=_restore_pattern_selection,
        verify_builder=lambda params: ("selected", params["index"]),
    ),
    _persistent_write_spec(
        domain="pattern",
        action="rename",
        validator=_validate_pattern_name,
        command=protocol.CMD_PATTERN_RENAME,
        snapshot_scope_builder=_pattern_scope,
        restore_builder=_restore_pattern_name,
    ),
    _persistent_write_spec(
        domain="pattern",
        action="set_color",
        validator=_validate_pattern_color,
        command=protocol.CMD_PATTERN_SET_COLOR,
        snapshot_scope_builder=_pattern_scope,
        restore_builder=_restore_pattern_color,
    ),
    _persistent_write_spec(
        domain="pattern",
        action="set_length",
        validator=_validate_pattern_length,
        command=protocol.CMD_PATTERN_SET_LENGTH,
        snapshot_scope_builder=_pattern_scope,
        restore_builder=_restore_pattern_length,
    ),
    _read_spec(
        domain="playlist",
        action="get",
        validator=_validate_playlist_track_param,
        command=protocol.CMD_PLAYLIST_GET_TRACK,
    ),
    _read_spec(
        domain="playlist",
        action="list",
        validator=_optional_page_start,
        command=protocol.CMD_PLAYLIST_LIST_TRACKS,
    ),
    _persistent_write_spec(
        domain="playlist",
        action="select",
        validator=_validate_playlist_track_select,
        command=protocol.CMD_PLAYLIST_SELECT_TRACK,
        snapshot_scope_builder=_playlist_track_scope,
        restore_builder=_restore_playlist_track_bool(
            protocol.CMD_PLAYLIST_SELECT_TRACK, "selected"
        ),
        verify_builder=lambda params: ("selected", params["state"]),
    ),
    _persistent_write_spec(
        domain="playlist",
        action="set_color",
        validator=_validate_playlist_track_color,
        command=protocol.CMD_PLAYLIST_SET_COLOR,
        snapshot_scope_builder=_playlist_track_scope,
        restore_builder=_restore_playlist_track_color,
    ),
    _persistent_write_spec(
        domain="playlist",
        action="set_mute",
        validator=_validate_playlist_track_bool,
        command=protocol.CMD_PLAYLIST_SET_MUTE,
        snapshot_scope_builder=_playlist_track_scope,
        restore_builder=_restore_playlist_track_bool(protocol.CMD_PLAYLIST_SET_MUTE, "mute"),
        verify_builder=lambda params: ("mute", params["state"]),
    ),
    _persistent_write_spec(
        domain="playlist",
        action="set_name",
        validator=_validate_playlist_track_name,
        command=protocol.CMD_PLAYLIST_SET_NAME,
        snapshot_scope_builder=_playlist_track_scope,
        restore_builder=_restore_playlist_track_name,
    ),
    _persistent_write_spec(
        domain="playlist",
        action="set_solo",
        validator=_validate_playlist_track_bool,
        command=protocol.CMD_PLAYLIST_SET_SOLO,
        snapshot_scope_builder=_playlist_track_scope,
        restore_builder=_restore_playlist_track_bool(protocol.CMD_PLAYLIST_SET_SOLO, "solo"),
        verify_builder=lambda params: ("solo", params["state"]),
    ),
    _read_spec(
        domain="effect",
        action="get_slot",
        validator=_validate_effect_slot,
        command=protocol.CMD_MIXER_GET_SLOT,
    ),
    _read_spec(
        domain="effect",
        action="get_track_slots_enabled",
        validator=_validate_track_slots_param,
        command=protocol.CMD_MIXER_GET_TRACK_SLOTS,
    ),
    _persistent_write_spec(
        domain="effect",
        action="set_slot_enabled",
        validator=_validate_effect_slot_enabled,
        command=protocol.CMD_MIXER_SET_SLOT_ENABLED,
        snapshot_scope_builder=_effect_slot_scope,
        restore_builder=_restore_effect_slot_enabled,
        verify_builder=lambda params: ("enabled", params["enabled"]),
    ),
    _persistent_write_spec(
        domain="effect",
        action="set_slot_mix",
        validator=_validate_effect_slot_mix,
        command=protocol.CMD_MIXER_SET_SLOT_MIX,
        snapshot_scope_builder=_effect_slot_scope,
        restore_builder=_restore_effect_slot_mix,
    ),
    _persistent_write_spec(
        domain="effect",
        action="set_track_slots_enabled",
        validator=_validate_track_slots_enabled,
        command=protocol.CMD_MIXER_SET_TRACK_SLOTS,
        snapshot_scope_builder=_track_slots_scope,
        restore_builder=_restore_track_slots_enabled,
        verify_builder=lambda params: ("enabled", params["enabled"]),
    ),
    _read_spec(
        domain="eq",
        action="get",
        validator=_validate_eq_track,
        command=protocol.CMD_MIXER_GET_EQ,
    ),
    _persistent_write_spec(
        domain="eq",
        action="set_band",
        validator=_validate_eq_band,
        command=protocol.CMD_MIXER_SET_EQ,
        snapshot_scope_builder=_eq_scope,
        restore_builder=_restore_eq_band,
    ),
    _read_spec(
        domain="plugin",
        action="get_param",
        validator=_validate_plugin_param_read,
        command=protocol.CMD_PLUGIN_GET_PARAM,
    ),
    _read_spec(
        domain="plugin",
        action="list",
        validator=_validate_plugin_track,
        command=protocol.CMD_PLUGIN_LIST,
    ),
    _read_spec(
        domain="plugin",
        action="list_params",
        validator=_validate_plugin_params_read,
        command=protocol.CMD_PLUGIN_GET_PARAMS,
    ),
    _persistent_write_spec(
        domain="plugin",
        action="set_param",
        validator=_validate_plugin_param_write,
        command=protocol.CMD_PLUGIN_SET_PARAM,
        snapshot_scope_builder=_plugin_param_scope,
        restore_builder=_restore_plugin_param,
        verify_builder=lambda params: ("v", round(float(params["value"]), 4)),
    ),
    _read_spec(
        domain="transport",
        action="get_play_state",
        validator=_validate_empty,
        command=protocol.CMD_GET_PLAY_STATE,
    ),
    _read_spec(
        domain="transport",
        action="get_song_position",
        validator=_validate_empty,
        command=protocol.CMD_GET_SONG_POS,
    ),
    _read_spec(
        domain="transport",
        action="get_tempo",
        validator=_validate_empty,
        command=protocol.CMD_GET_TEMPO,
    ),
    _read_spec(
        domain="transport",
        action="get_time_signature",
        validator=_validate_empty,
        command=protocol.CMD_GET_TIME_SIG,
    ),
    _transient_spec(
        domain="transport",
        action="play",
        validator=_validate_empty,
        command=protocol.CMD_PLAY,
    ),
    _transient_spec(
        domain="transport",
        action="record",
        validator=_validate_empty,
        command=protocol.CMD_RECORD,
    ),
    _persistent_write_spec(
        domain="transport",
        action="set_tempo",
        validator=_validate_tempo,
        command=protocol.CMD_SET_TEMPO,
        snapshot_scope_builder=lambda _params: "tempo",
        restore_builder=_restore_tempo,
    ),
    _transient_spec(
        domain="transport",
        action="set_song_position",
        validator=_validate_song_position,
        command=protocol.CMD_SET_SONG_POS,
    ),
    _persistent_write_spec(
        domain="transport",
        action="set_time_signature",
        validator=_validate_time_signature,
        command=protocol.CMD_SET_TIME_SIG,
        snapshot_scope_builder=lambda _params: "time_signature",
        restore_builder=_restore_time_signature,
    ),
    _transient_spec(
        domain="transport",
        action="stop",
        validator=_validate_empty,
        command=protocol.CMD_STOP,
    ),
    _transient_spec(
        domain="transport",
        action="toggle_play",
        validator=_validate_empty,
        command=protocol.CMD_TOGGLE_PLAY,
    ),
)


OPERATION_REGISTRY = OperationRegistry(_DEFAULT_SPECS)


def get_operation(domain: str, action: str) -> OperationSpec:
    return OPERATION_REGISTRY.get(domain, action)


def prepare_operation(domain: str, action: str, params: Mapping[str, Any]) -> PreparedOperation:
    return OPERATION_REGISTRY.prepare(domain, action, params)


def list_operations() -> list[OperationSpec]:
    return OPERATION_REGISTRY.list_specs()


__all__ = [
    "BatchCategory",
    "OPERATION_REGISTRY",
    "OperationCommand",
    "OperationRegistry",
    "OperationSpec",
    "OperationValidationError",
    "PreparedOperation",
    "SafetyClass",
    "get_operation",
    "list_operations",
    "prepare_operation",
]
