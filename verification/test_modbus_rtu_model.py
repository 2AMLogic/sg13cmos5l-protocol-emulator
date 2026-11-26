#!/usr/bin/env python3
"""Self-test for the independent Modbus RTU model (issue #446).

Stdlib-only, no DUT: pins down the model's own claims -- the CRC-16
check value, the server behaviour it grades against, the 8N2 decode of
a synthesized waveform (including the retimed negative control the bench
reuses), and the DE/silence bounds -- so a model regression fails here
before it can mis-grade a bench run.

Not a cocotb module; run directly or via `npm run lint`:
    python3 verification/test_modbus_rtu_model.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reference_models.modbus_rtu import (  # noqa: E402
    BIT_TOL_PCT,
    FRAME_BITS,
    SERVER_ADDRESS,
    ServerState,
    char_value_bits,
    check_de_window,
    check_silence,
    crc16_modbus,
    decode_frame,
    encode_frame,
    frame_bytes,
)

_failures = []


def check(name, got, want):
    if got != want:
        _failures.append(f"{name}: got {got!r}, want {want!r}")


def check_true(name, cond, detail=""):
    if not cond:
        _failures.append(f"{name}: {detail}")


# --- CRC-16/MODBUS ---------------------------------------------------------
check("check value of '123456789'", hex(crc16_modbus(b"123456789")), "0x4b37")
check("empty frame crc", hex(crc16_modbus(b"")), "0xffff")
# frame_bytes appends low byte first; the residual over a whole frame is 0
probe = frame_bytes(bytes([SERVER_ADDRESS, 0x03, 0, 0, 0, 2]))
check("frame length", len(probe), 8)
check("residual is zero", crc16_modbus(probe), 0)
check("low byte first", probe[6], crc16_modbus(probe[:6]) & 0xFF)
# the model's CRC is deliberately a different computation than the
# firmware's bitwise loop: verify it against a bitwise reference
crc = 0xFFFF
for b in probe[:6]:
    crc ^= b
    for _ in range(8):
        crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
check("table vs bitwise", crc, crc16_modbus(probe[:6]))

# --- the server this model grades against ---------------------------------
state = ServerState()
read = frame_bytes(bytes([SERVER_ADDRESS, 0x03, 0, 0, 0, 2]))
check("0x03 initial map", state.reply(read),
      frame_bytes(bytes([0x11, 0x03, 0x04, 0xDE, 0xAD, 0xBE, 0xEF])))
bad = bytearray(read)
bad[0] ^= 1
check("bad crc silence", state.reply(bytes(bad)), None)
check("wrong address silence",
      state.reply(frame_bytes(bytes([0x12, 0x03, 0, 0, 0, 2]))), None)
check("bad count silence",
      state.reply(frame_bytes(bytes([0x11, 0x03, 0, 0, 0, 1]))), None)
check("bad start silence",
      state.reply(frame_bytes(bytes([0x11, 0x03, 0, 1, 0, 2]))), None)
check("unsupported fc silence",
      state.reply(frame_bytes(bytes([0x11, 0x10, 0, 0, 0, 2]))), None)
write = frame_bytes(bytes([0x11, 0x06, 0, 1, 0x12, 0x34]))
check("0x06 echo", state.reply(write), write)
check("map after write", state.reply(read),
      frame_bytes(bytes([0x11, 0x03, 0x04, 0xDE, 0xAD, 0x12, 0x34])))
check("0x06 register 2 silence",
      state.reply(frame_bytes(bytes([0x11, 0x06, 0, 2, 0, 0]))), None)

# --- 8N2 characters --------------------------------------------------------
check("start bit", char_value_bits(0x00)[0], 0)
check("stops", char_value_bits(0x00)[9:], [1, 1])
check("lsb first", char_value_bits(0x01)[1:3], [1, 0])

# --- decode round-trip on a synthesized capture ---------------------------
BIT_NS = 434 * 20.0


def synthesize(resp: bytes, de_open=200.0, de_hold=3000.0):
    # build a response-shaped capture directly (the model's encode_frame
    # builds requests; responses differ only in who drives)
    tr, t = [], 3000.0
    for byte in resp:
        for level in char_value_bits(byte):
            tr.append((t, level))
            t += BIT_NS
        tr.append((t, 1))
    end = t
    from bisect import bisect_right
    tr_times = [x[0] for x in tr]

    def tx_at(x):
        i = bisect_right(tr_times, x) - 1
        return tr[i][1] if i >= 0 else 1

    times = [float(x) for x in range(0, int(end + de_hold), 10)]
    uo = [((2 if de_open <= x < end + de_hold else 0) | tx_at(x)) for x in times]
    return times, uo, end


resp = frame_bytes(bytes([0x11, 0x03, 0x04, 0xDE, 0xAD, 0xBE, 0xEF]))
times, uo, end = synthesize(resp)
reps = decode_frame(times, uo, BIT_NS)
check("one window", len(reps), 1)
check_true("decodes", reps[0].ok,
           f"errors: {[ (c.slot_errors, c.spacing_errors) for c in reps[0].chars ]}")
check("bytes", reps[0].decoded(), resp)
check_true("de window clean", not check_de_window(reps[0], BIT_NS),
           str(check_de_window(reps[0], BIT_NS)))
check_true("silence bound holds at 4 chars",
           not check_silence(reps[0].first_start_ns - 4.0 * 11 * BIT_NS,
                             reps[0].first_start_ns, BIT_NS))
errs = check_silence(reps[0].first_start_ns, reps[0].first_start_ns + 100, BIT_NS)
check_true("silence bound trips when too fast", bool(errs), "no error")

# the retimed negative control: 4% still decodes the bytes (mid-bit
# samples stay inside their stretched bits) but fails the timing bounds
scaled = [x * 1.04 for x in times]
reps2 = decode_frame(scaled, uo, BIT_NS)
check("retimed bytes", reps2[0].bytes, list(resp))
check_true("retimed timing fails",
           any(c.slot_errors or c.spacing_errors for c in reps2[0].chars),
           "the negative control did not trip")
check("tolerance stated", BIT_TOL_PCT, 2.5)
check("frame bits", FRAME_BITS, 11)

if _failures:
    print(f"modbus_rtu model self-test: {len(_failures)} failure(s)")
    for f in _failures:
        print("  FAIL", f)
    sys.exit(1)
print("modbus_rtu model self-test: all checks passed")
