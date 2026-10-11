"""Post-layout entry point for the I2C write / repeated START / read /
clock-stretch firmware bench (issue #217).

Runs `test_firmware_i2c_sr.py`'s tests, byte-unchanged, with the
routed-delay alignment of `sdf_protocol_alignment` (see that module for
what is patched and why). Named only by `flow/run-post-layout-sdf.sh
--suite protocols`; no RTL request names it.

Patched when `PE_ALIGN_*` is set: `RisingEdge` in `test_firmware_i2c_sr`
(the reactive ACK / read-data / stretching peripheral) and in
`test_firmware_uart` (home of the shared capture) to the observe point, and
`test_firmware_i2c_sr.capture_pin_bits` (monitored for pin delay). The
bench's own timing negative controls run on the routed netlist unchanged:
its capture compressed 0.9x must fail t_LOW, the f_SCL period and
t_SU;STA, and firmware with the repeated-START setup WAIT one cycle (and
half) short must fail t_SU;STA alone.
"""

import sdf_protocol_alignment as _align
import test_firmware_i2c as _i2c_helpers
import test_firmware_i2c_sr as bench
import test_firmware_uart as _capture_home

PROTOCOL = "i2c_sr"

REPORT = _align.install(
    PROTOCOL,
    bench,
    edge_modules=(bench, _capture_home),
    capture_modules=(bench,),
    capture_source=_capture_home,
    period_modules=(bench, _i2c_helpers, _capture_home),
)
TESTS = _align.register(bench, globals())
