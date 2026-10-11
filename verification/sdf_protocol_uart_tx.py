"""Post-layout entry point for the UART TX firmware bench (issue #217).

Runs `test_firmware_uart.py`'s tests, byte-unchanged, with the routed-delay
alignment of `sdf_protocol_alignment` (see that module for what is
patched and why). Named only by `flow/run-post-layout-sdf.sh --suite
protocols`; no RTL request names it.

Patched when `PE_ALIGN_*` is set: `test_firmware_uart.RisingEdge` (the
capture's edges, to the observe point) and `test_firmware_uart.
capture_pin_bits` (monitored for pin delay). The bench's own timing
negative control -- its captured TX waveform stretched 1.025x must fail
the row-10 drift bound -- runs on the routed capture unchanged.
"""

import sdf_protocol_alignment as _align
import test_firmware_uart as bench

PROTOCOL = "uart_tx"

REPORT = _align.install(
    PROTOCOL,
    bench,
    edge_modules=(bench,),
    capture_modules=(bench,),
    capture_source=bench,
    period_modules=(bench,),
)
TESTS = _align.register(bench, globals())
