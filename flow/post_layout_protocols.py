#!/usr/bin/env python3
"""Protocol inventory, per-run grading and per-corner aggregation for
`flow/run-post-layout-sdf.sh --suite protocols` (issue #217).

The runner owns acquisition, SDF normalization, the SDC-derived alignment
and the serial klt dispatch; this file owns the decisions that have to be
testable without a routed run (`flow/test_post_layout_protocols.py`):

- which protocols exist and which testbench module, bench and test names
  each one is (`PROTOCOLS`), and which subset a command line selects;
- whether one (corner, protocol) run passed: the klt envelope, the SDF
  annotation flag, every expected test passed (none skipped, none
  missing), and the wrapper's protocol report (captures made, every output
  transition before the observe point, real pin delay observed, required
  timing controls run and failed as required);
- the per-protocol, per-corner matrix, which is complete or the suite
  fails, and the stated SRAM / pad / scope limitations.

Zero dependencies beyond the Python 3 standard library. Subcommands:

    select [--protocol NAME ...]           ordered protocol list, one per line
    module NAME                            the testbench module for NAME
    grade --protocol P --corner C --envelope F --rc N --report F
          [--elapsed S] --out F             one entry; exit 1 if it failed
    aggregate --entries-dir D --corners C... --protocols P...
          --alignment F --renames F --macro-types T...
          --normalization F... --out F      the results document; exit 1
                                            unless every cell passed

Exit codes: 0 pass, 1 a graded failure, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

#: The protocols the harness can run, in the order it runs them. Each
#: bench module is one `flow/run-firmware-gate-level.sh` also runs (the
#: zero-delay gate-level inventory; `test_firmware_i2c_sr` is its `--full`
#: addition), checked by the tests.
PROTOCOLS = {
    "uart_tx": {
        "testbench_module": "sdf_protocol_uart_tx",
        "bench_module": "test_firmware_uart",
        "expected_tests": (
            "test_committed_image_is_fresh",
            "test_uart_frames_pass_independent_reference_model",
            "test_reference_model_negative_control_still_fails",
        ),
        # one capture of the whole two-frame program
        "min_captures": 1,
        "required_controls": {},
        "bench_controls": "captured TX waveform stretched 1.025x must fail the row-10 drift bound",
    },
    "spi": {
        "testbench_module": "sdf_protocol_spi",
        "bench_module": "test_firmware_spi",
        "expected_tests": (
            "test_committed_images_are_fresh",
            "test_all_four_modes_pass_independent_reference_model",
            "test_reference_model_negative_controls_still_fail",
        ),
        # one capture per mode
        "min_captures": 4,
        # two DUT bursts per mode, each re-graded at 0.9x the ceiling
        "required_controls": {"spi_ceiling_compressed": 8},
        "bench_controls": "captured ceiling burst under each wrong mode must not round-trip",
    },
    "i2c_sr": {
        "testbench_module": "sdf_protocol_i2c_sr",
        "bench_module": "test_firmware_i2c_sr",
        "expected_tests": (
            "test_sr_images_fresh",
            "test_sr_exact_programs_pass_model_with_negative_controls",
            "test_sr_poll_programs_stretch",
            "test_sr_uio_od_left_at_reset_cannot_drive_the_bus",
            "test_sr_model_nominal_repeated_start_passes",
        ),
        # exact: 2 x (golden + 2 mutants); poll: 2 x (plain, stretched,
        # exact-under-stretch); UIO_OD control: 4
        "min_captures": 16,
        "required_controls": {},
        "bench_controls": (
            "captured lines compressed 0.9x must fail t_LOW, f_SCL and t_SU;STA; "
            "firmware t_SU;STA WAIT 1 and SUSTA/2 cycles short must fail t_SU;STA alone"
        ),
    },
}

DEFAULT_ORDER = tuple(PROTOCOLS)

FLOW = (
    "routed netlist, SDF and SDC: Tiny Tapeout LibreLane gds workflow artifacts; "
    "simulation: Icarus + cocotb through klt functional-verification with options.sdf. "
    "No synthesis or STA number is produced by this harness."
)


class UsageError(Exception):
    pass


def select(requested) -> list:
    """The protocols to run, in inventory order, without duplicates.
    Empty request -> all of them. Unknown name -> UsageError."""
    if not requested:
        return list(DEFAULT_ORDER)
    unknown = sorted({p for p in requested if p not in PROTOCOLS})
    if unknown:
        raise UsageError(
            f"unknown protocol(s) {unknown}; known: {', '.join(DEFAULT_ORDER)}"
        )
    wanted = set(requested)
    return [p for p in DEFAULT_ORDER if p in wanted]


def run_matrix(corners, protocols) -> list:
    """The serial dispatch order: corner-major, protocols in inventory
    order inside each corner."""
    if not corners:
        raise UsageError("no corners")
    if len(set(corners)) != len(corners):
        raise UsageError(f"duplicate corner in {list(corners)}")
    order = select(protocols)
    return [(corner, protocol) for corner in corners for protocol in order]


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return None


def grade(protocol, corner, envelope, run_rc, report, elapsed_s=None) -> dict:
    """Grade one (corner, protocol) run. `envelope` and `report` are the
    parsed klt response and wrapper report (None when missing). Returns the
    entry; `entry["verdict"]` is "pass" only if no reason was found."""
    spec = PROTOCOLS[protocol]
    reasons = []
    entry = {
        "corner": corner,
        "protocol": protocol,
        "testbench_module": spec["testbench_module"],
        "bench_module": spec["bench_module"],
        "run_rc": run_rc,
        "elapsed_s": elapsed_s,
        "sdf_annotated": False,
        "status": None,
        "tests": None,
        "pin_delay_ps": None,
        "captures": None,
        "timing_controls": None,
        "bench_timing_controls": spec["bench_controls"],
    }

    if run_rc != 0:
        reasons.append(f"klt exited {run_rc}")

    if not isinstance(envelope, dict):
        reasons.append("missing result: no parsable klt functional-verification response")
    else:
        sdf = (envelope.get("environment") or {}).get("sdf")
        entry["sdf_annotated"] = bool(isinstance(sdf, dict) and sdf.get("annotated") is True)
        if not entry["sdf_annotated"]:
            reasons.append(
                "environment.sdf.annotated is not true (absent or false): "
                "the run may have fallen back to zero delay"
            )
        entry["status"] = envelope.get("status")
        if entry["status"] != "pass":
            reasons.append(f"klt status {entry['status']!r}, not 'pass'")
        if envelope.get("testbench") not in (None, spec["testbench_module"]):
            reasons.append(
                f"response names testbench {envelope.get('testbench')!r}, "
                f"expected {spec['testbench_module']!r}"
            )
        tests = {}
        for test in envelope.get("tests") or []:
            if isinstance(test, dict) and "name" in test:
                tests[test["name"]] = test.get("status")
        entry["tests"] = tests
        for name in spec["expected_tests"]:
            if name not in tests:
                reasons.append(f"missing result: test {name} not reported")
            elif tests[name] != "passed":
                reasons.append(f"test {name} {tests[name]}")
        extra = sorted(set(tests) - set(spec["expected_tests"]))
        if extra:
            reasons.append(f"unexpected test(s) {extra}: the protocol inventory is stale")
        for key in ("failed_count", "skipped_count"):
            if envelope.get(key) not in (0, None):
                reasons.append(f"{key} {envelope.get(key)}")

    if not isinstance(report, dict):
        reasons.append("missing result: no parsable protocol report from the testbench wrapper")
    else:
        if report.get("protocol") != protocol:
            reasons.append(f"protocol report is for {report.get('protocol')!r}, not {protocol!r}")
        if not report.get("alignment_ps"):
            reasons.append("protocol report carries no alignment: the wrapper ran unaligned")
        captures = report.get("captures") or 0
        entry["captures"] = captures
        if captures < spec["min_captures"]:
            reasons.append(f"{captures} capture(s), at least {spec['min_captures']} required")
        violations = report.get("contract_violation_count") or 0
        if violations:
            reasons.append(
                f"{violations} output transition(s) not before the observe point: "
                f"{(report.get('contract_violations') or [])[:3]}"
            )
        events = report.get("pin_events") or {}
        entry["pin_delay_ps"] = events
        total = sum((e or {}).get("count") or 0 for e in events.values())
        max_delay = max(
            [(e or {}).get("max_delay_ps") or 0 for e in events.values()] or [0]
        )
        if total == 0:
            reasons.append("no output transition observed at the pins")
        elif max_delay <= 0:
            reasons.append(
                "every observed output transition had zero delay after the clk edge: "
                "back-annotation had no effect at the pins"
            )
        controls = report.get("timing_controls") or {}
        entry["timing_controls"] = controls
        for name, minimum in spec["required_controls"].items():
            got = controls.get(name) or {}
            run, failed = got.get("run") or 0, got.get("failed_as_required") or 0
            if run < minimum:
                reasons.append(f"timing control {name} ran {run} time(s), at least {minimum} required")
            if failed != run:
                reasons.append(f"timing control {name}: {run - failed} of {run} did not fail as required")

    entry["reasons"] = reasons
    entry["verdict"] = "pass" if not reasons else "fail"
    return entry


def limitations(macro_types, normalization_reports, renames) -> dict:
    """What this simulation does NOT time, stated per run set."""
    macro_blocks = []
    for path, doc in normalization_reports:
        for block in (doc or {}).get("macro_cell_blocks_dropped") or []:
            macro_blocks.append({
                "normalization_report": path,
                "cell_type": block.get("cell_type"),
                "iopath_entries_dropped": block.get("iopath_entries_dropped"),
                "timingcheck_entries_dropped": block.get("timingcheck_entries_dropped"),
            })
    if macro_types:
        sram = {
            "present": True,
            "macro_types": sorted(macro_types),
            "model": "zero-delay FUNCTIONAL behavioural model (rtl/vendor, `define FUNCTIONAL scoped to the macro files)",
            "sdf": "macro CELL blocks removed by normalization; no SDF delay or timing check binds to the macro",
            "dropped_per_corner": macro_blocks,
            "timing_covered_by": "LibreLane post-route STA (gds workflow), not this simulation",
            "macro_instance_renames": [r for r in renames if r.get("kind", "macro") == "macro"],
        }
    else:
        sram = {"present": False, "model": "no hard macro instantiated by the routed netlist"}
    return {
        "sram": sram,
        "pads": {
            "uio": "verification/uio_pads.py: zero-delay combinational pad resolution (pulls, open-drain, contention); no pad propagation delay, slew, RC rise or drive strength",
            "io_cells": "outputs are observed at the tt_um_* macro boundary; Tiny Tapeout IO pad cells, mux and package are not in the netlist",
        },
        "observe_point": "captures and reactive peripherals read at drive offset - 1 ns after each clk pin edge (earlier than the SDC sample point); every uo_out/uio_out/uio_oe transition must reach the pin strictly before it",
        "claim_scope": "standard-cell SDF annotation of the routed tt_um_* netlist only; no full-chip timing-closure claim",
    }


def aggregate(entries, corners, protocols, alignment, limits) -> dict:
    """The results document: every (corner, protocol) cell, a matrix, and
    the overall verdict (pass only if every expected cell passed exactly
    once)."""
    expected = run_matrix(corners, protocols)
    cells = {}
    problems = []
    for entry in entries:
        key = (entry.get("corner"), entry.get("protocol"))
        if key not in expected:
            problems.append(f"unexpected result for {key}")
            continue
        if key in cells:
            problems.append(f"duplicate result for {key}")
            continue
        cells[key] = entry
    matrix = {}
    for corner, protocol in expected:
        entry = cells.get((corner, protocol))
        verdict = "missing" if entry is None else entry.get("verdict", "fail")
        matrix.setdefault(protocol, {})[corner] = verdict
        if entry is None:
            problems.append(f"missing result for corner {corner}, protocol {protocol}")
    failed = [
        f"{c}/{p}: {'; '.join(cells[(c, p)].get('reasons') or ['fail'])}"
        for c, p in expected
        if (c, p) in cells and cells[(c, p)].get("verdict") != "pass"
    ]
    overall = "pass" if not problems and not failed else "fail"
    return {
        "schema": "pe.post_layout_sdf_protocols/1",
        "suite": "protocols",
        "flow": FLOW,
        "corners": list(corners),
        "protocols": select(protocols),
        "alignment": alignment,
        "limitations": limits,
        "matrix": matrix,
        "overall": overall,
        "problems": problems,
        "failures": failed,
        "runs": [cells[k] for k in expected if k in cells],
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _write(path, doc):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, indent=2)
        handle.write("\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("select")
    p.add_argument("--protocol", action="append", default=[])

    p = sub.add_parser("module")
    p.add_argument("protocol")

    p = sub.add_parser("grade")
    p.add_argument("--protocol", required=True)
    p.add_argument("--corner", required=True)
    p.add_argument("--envelope", required=True)
    p.add_argument("--rc", type=int, required=True)
    p.add_argument("--report", required=True)
    p.add_argument("--elapsed", type=int, default=None)
    p.add_argument("--out", required=True)

    p = sub.add_parser("aggregate")
    p.add_argument("--entries-dir", required=True)
    p.add_argument("--corners", nargs="+", required=True)
    p.add_argument("--protocols", nargs="+", required=True)
    p.add_argument("--alignment", required=True)
    p.add_argument("--renames", required=True)
    p.add_argument("--macro-types", nargs="*", default=[])
    p.add_argument("--normalization", nargs="*", default=[])
    p.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    try:
        if args.cmd == "select":
            print("\n".join(select(args.protocol)))
            return 0
        if args.cmd == "module":
            if args.protocol not in PROTOCOLS:
                raise UsageError(f"unknown protocol {args.protocol!r}")
            print(PROTOCOLS[args.protocol]["testbench_module"])
            return 0
        if args.cmd == "grade":
            if args.protocol not in PROTOCOLS:
                raise UsageError(f"unknown protocol {args.protocol!r}")
            entry = grade(
                args.protocol, args.corner, _load_json(args.envelope), args.rc,
                _load_json(args.report), args.elapsed,
            )
            _write(args.out, entry)
            for reason in entry["reasons"]:
                print(f"   FAIL {args.corner}/{args.protocol}: {reason}", file=sys.stderr)
            return 0 if entry["verdict"] == "pass" else 1
        if args.cmd == "aggregate":
            entries = []
            for path in sorted(Path(args.entries_dir).glob("*.json")):
                doc = _load_json(path)
                if isinstance(doc, dict):
                    entries.append(doc)
            alignment = _load_json(args.alignment)
            renames = (_load_json(args.renames) or {}).get("renames") or []
            norms = [(n, _load_json(n)) for n in args.normalization]
            limits = limitations([t for t in args.macro_types if t], norms, renames)
            doc = aggregate(entries, args.corners, args.protocols, alignment, limits)
            _write(args.out, doc)
            for line in doc["problems"] + doc["failures"]:
                print(f"   {line}", file=sys.stderr)
            return 0 if doc["overall"] == "pass" else 1
    except UsageError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
