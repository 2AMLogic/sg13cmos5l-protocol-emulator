// Fixture toplevel for the reference-model validation bench
// (verification/test_protocol_models.py, issue #25).
//
// This is a FIXTURE, not the design: the reference models of
// verification-plan.md section 4 are pure-Python waveform judges with no
// DUT to observe yet (the ISA core is issue #18, firmware is #22/#23),
// and cocotb needs *some* HDL toplevel to elaborate.  This module exists
// only so `klt functional-verification` can host the suite; no pin of
// this fixture is driven or checked by the bench, and no result recorded
// against it is a claim about `src/` or `rtl/` logic.  The DUT-facing
// suites that will one day run against the real core use the same
// reference models with a different toplevel and request.
`timescale 1ns/1ps
module model_validation_top (
    input wire clk,
    input wire rst_n
);
    // Intentionally empty: the fixture has no behavior to check.
endmodule
