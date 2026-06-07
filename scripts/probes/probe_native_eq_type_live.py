#!/usr/bin/env python3
"""LIVE: rollback-safe native mixer EQ type mapping probe.

This is a constrained probe, not a user-facing tool. It tests documented
REC_Mixer_EQ_Type write variants for one mixer track/band, restores each
attempt immediately, and reports whether any variant read back as the target
type.

Default target is mixer track 8 / band 0 / high-pass type value 3, matching the
Drums high-pass investigation.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("FLSTUDIO_MCP_TRANSPORT", "tcp")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fl_studio_mcp import protocol, safety  # noqa: E402
from fl_studio_mcp.connection import FLCommandFailed, get_bridge  # noqa: E402

EXPECTED_BUILD = "channels-v39"
HIGH_PASS_TYPE = 3


@dataclass(frozen=True)
class Variant:
    label: str
    value: int | float
    flags: str


def _variants(target_type: int) -> list[Variant]:
    norm = float(target_type) / 7.0
    midi_65535 = int(round(norm * 65535))
    midi_65536 = int(round(norm * 65536))
    out = [
        Variant("raw-int-control", int(target_type), "control"),
        Variant("raw-int-update", int(target_type), "update"),
        Variant("raw-float-control", float(target_type), "control"),
        Variant("norm-control", norm, "control"),
        Variant("norm-update", norm, "update"),
        Variant("midi-65535", midi_65535, "midi"),
        Variant("midi-65536", midi_65536, "midi"),
    ]
    for candidate in range(8):
        if candidate != target_type:
            out.append(Variant(f"candidate-{candidate}-control", candidate, "control"))
    return out


def _band(eq: dict, band: int) -> dict:
    for row in eq.get("bands", []):
        if int(row.get("band", -1)) == int(band):
            return row
    raise ValueError(f"band {band} not present in EQ payload: {eq}")


def _restore_params(track: int, band: int, before_band: dict, variant: Variant) -> dict:
    return {
        "command": protocol.CMD_MIXER_PROBE_EQ_TYPE,
        "params": {
            "track": track,
            "band": band,
            "value": int(before_band.get("type", 0)),
            "flags": variant.flags,
        },
    }


def _run_variant(bridge, *, track: int, band: int, target_type: int, variant: Variant) -> bool:
    before = bridge.call(protocol.CMD_MIXER_GET_EQ, {"track": track})
    before_band = _band(before, band)
    try:
        result = safety.safe_write(
            bridge,
            tool="native_eq_type_mapping_probe",
            scope=f"mixer_eq:{track}",
            command=protocol.CMD_MIXER_PROBE_EQ_TYPE,
            params={"track": track, "band": band, "value": variant.value, "flags": variant.flags},
            build_restore=lambda _snap, bb=before_band, v=variant: _restore_params(
                track, band, bb, v
            ),
        )
    except FLCommandFailed as exc:
        print(f"[INCONCLUSIVE] {variant.label}: command failed: {exc}")
        return False

    after = bridge.call(protocol.CMD_MIXER_GET_EQ, {"track": track})
    after_band = _band(after, band)
    type_after = int(after_band.get("type", -1))
    ok = type_after == target_type
    status = "PASS" if ok else "MISS"
    print(
        f"[{status}] {variant.label}: value={variant.value!r} flags={variant.flags!r} "
        f"type_before={before_band.get('type')} type_after={type_after} "
        f"probe={result.get('after', {}).get('probe')}"
    )

    rb = safety.rollback_last_change(bridge)
    if not rb.get("ok"):
        print(f"[FAIL] {variant.label}: rollback failed: {rb}")
        raise SystemExit(1)
    restored = bridge.call(protocol.CMD_MIXER_GET_EQ, {"track": track})
    restored_band = _band(restored, band)
    if int(restored_band.get("type", -1)) != int(before_band.get("type", 0)):
        print(f"[FAIL] {variant.label}: restore mismatch: {restored}")
        raise SystemExit(1)
    return ok


def _leave_variant_for_visual(
    bridge, *, track: int, band: int, variant: Variant, target_type: int
) -> None:
    before = bridge.call(protocol.CMD_MIXER_GET_EQ, {"track": track})
    before_band = _band(before, band)
    result = safety.safe_write(
        bridge,
        tool="native_eq_type_mapping_visual_check",
        scope=f"mixer_eq:{track}",
        command=protocol.CMD_MIXER_PROBE_EQ_TYPE,
        params={"track": track, "band": band, "value": variant.value, "flags": variant.flags},
        build_restore=lambda _snap, bb=before_band, v=variant: _restore_params(track, band, bb, v),
    )
    after = bridge.call(protocol.CMD_MIXER_GET_EQ, {"track": track})
    print(
        "[LEFT_FOR_VISUAL_CHECK] "
        f"label={variant.label} target_type={target_type} change_id={result.get('change_id')}"
    )
    print(f"BEFORE {before}")
    print(f"AFTER {after}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--track", type=int, default=8)
    parser.add_argument("--band", type=int, default=0)
    parser.add_argument("--target-type", type=int, default=HIGH_PASS_TYPE)
    parser.add_argument(
        "--leave-variant",
        help="Variant label to leave in FL for visual inspection; use change_id rollback later.",
    )
    args = parser.parse_args()

    bridge = get_bridge()
    pong = bridge.call(protocol.CMD_PING, {})
    print(f"FL: {pong.get('fl_version')} | build={pong.get('build')}")
    if pong.get("build") != EXPECTED_BUILD:
        print(
            f"[BLOCKED] Controller build is {pong.get('build')!r}; reload FL MIDI scripts "
            f"until fl_ping reports {EXPECTED_BUILD!r}."
        )
        return 2

    track = bridge.call(protocol.CMD_MIXER_GET_TRACK, {"index": args.track})
    eq = bridge.call(protocol.CMD_MIXER_GET_EQ, {"track": args.track})
    print(f"TARGET track={args.track} name={track.get('name')!r} band={args.band}")
    print(f"BEFORE {eq}")

    variants = _variants(args.target_type)
    by_label = {variant.label: variant for variant in variants}
    if args.leave_variant:
        variant = by_label.get(args.leave_variant)
        if variant is None:
            print(f"[FAIL] Unknown variant {args.leave_variant!r}; choices={sorted(by_label)}")
            return 1
        _leave_variant_for_visual(
            bridge, track=args.track, band=args.band, variant=variant, target_type=args.target_type
        )
        return 0

    hits = [
        variant.label
        for variant in variants
        if _run_variant(
            bridge,
            track=args.track,
            band=args.band,
            target_type=args.target_type,
            variant=variant,
        )
    ]
    print("\n=== Native EQ type probe summary ===")
    if hits:
        print(f"[PASS] Variants that read back as type {args.target_type}: {hits}")
        return 0
    print(f"[INCONCLUSIVE] No variant read back as type {args.target_type}.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
