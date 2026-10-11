"""Post-layout entry point for the SPI modes 0-3 firmware bench (issue #217).

Runs `test_firmware_spi.py`'s tests, byte-unchanged, with the routed-delay
alignment of `sdf_protocol_alignment` (see that module for what is
patched and why). Named only by `flow/run-post-layout-sdf.sh --suite
protocols`; no RTL request names it.

Patched when `PE_ALIGN_*` is set: `RisingEdge` in `test_firmware_spi` (the
reactive MISO peripheral) and in `test_firmware_uart` (home of the shared
capture) to the observe point; `test_firmware_spi.capture_pin_bits`
(monitored for pin delay); and `test_firmware_spi.check_burst`, which
returns the model's own report unchanged and additionally re-grades every
conformant burst compressed to 0.9x the f_clk/4 ceiling, which must fail
(`sdf_protocol_alignment.SPI_CEILING_CONTROL`) -- the timing control the
SPI bench's mode-based controls do not provide on the DUT capture.
"""

import sdf_protocol_alignment as _align
import test_firmware_spi as bench
import test_firmware_uart as _capture_home

PROTOCOL = "spi"

REPORT = _align.install(
    PROTOCOL,
    bench,
    edge_modules=(bench, _capture_home),
    capture_modules=(bench,),
    capture_source=_capture_home,
    period_modules=(bench, _capture_home),
    spi_check_burst=True,
)
TESTS = _align.register(bench, globals())
