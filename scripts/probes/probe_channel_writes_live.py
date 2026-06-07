import time

from fl_studio_mcp.connection import get_bridge


def test_live_api():
    b = get_bridge()
    print("Testing FL Studio API Probes...")

    # Probe 1: Get channel type constants
    print("\\n--- Track Types ---")
    res = b.call("api_probe", {"op": "dir", "module": "midi"})
    midi_names = res.get("names", [])
    if not midi_names:
        print("Could not get midi constants")

    # Try to evaluate midi.CT_AudioClip and midi.CT_Sampler
    # Wait, we can't eval directly, but we know they exist. Let's ask for channels list.
    res = b.call("channel_list")
    channels = res.get("channels", [])
    if channels:
        for ch in channels[:5]:
            print(f"Channel {ch['i']} '{ch['name']}': type_code={ch.get('type_code')}")
    else:
        print("Failed to list channels:", res)

    # Probe 2 & 3: Channel Rename and Target Write
    print("\\n--- Channel Writes ---")
    if channels:
        ch0 = channels[0]
        original_name = ch0["name"]

        res = b.call("channel_get", {"index": ch0["i"]})
        if res:
            original_target = res.get("target_fx_track", 0)
            print(f"Original Channel 0: '{original_name}', Target Mixer: {original_target}")

            # Write Name
            test_name = original_name + " (Test)"
            res2 = b.call("channel_set_name", {"channel": ch0["i"], "name": test_name})
            print(f"Set Name Result: {res2}")

            # Write Target
            test_target = original_target + 1 if original_target < 125 else 1
            res3 = b.call("channel_set_target", {"channel": ch0["i"], "track": test_target})
            print(f"Set Target Result: {res3}")

            time.sleep(0.5)

            # Readback
            res4 = b.call("channel_get", {"index": ch0["i"]})
            if res4:
                print(
                    f"Readback Channel 0: '{res4.get('name')}', Target Mixer: {res4.get('target_fx_track')}"
                )

            # Rollback
            b.call("channel_set_name", {"channel": ch0["i"], "name": original_name})
            b.call("channel_set_target", {"channel": ch0["i"], "track": original_target})
            print("Rollback applied.")


if __name__ == "__main__":
    test_live_api()
