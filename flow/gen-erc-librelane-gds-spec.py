#!/usr/bin/env python3
"""Generate flow/erc-librelane-gds.json, the `klt erc` supply spec for the
LibreLane GDS of record (issue #350, T1 item 11 part 1).

Run it with klt's own interpreter (it needs `klayout.db`):

    ~/.local/share/uv/tools/klayout-tools/bin/python -I \
        flow/gen-erc-librelane-gds-spec.py <gds> flow/erc-librelane-gds.json

Why a generator: `klt erc` ties[] cannot say "Activ NOT under pSD" (the
CMOS5L stdcells draw no nSD, so an n-well tap is an Activ inside NWell with
no pSD over it) and has no derived substrate region. Both are therefore
declared as caller assertions (`tap_boxes`, `well_boxes`) taken from the
GDS under test. They stay falsifiable: a box with no tap that reaches the
supply is an `erc.missing_tie`.
"""
import json
import sys

import klayout.db as db

TOP = "tt_um_2amlogic_protocol_emulator"
METALS = [("metal1", 8), ("metal2", 10), ("metal3", 30), ("metal4", 50)]


def boxes(region):
    out = []
    for poly in region.each():
        parts = [poly] if poly.num_points() == 4 else poly.decompose_trapezoids(
            db.Polygon.TD_simple)
        for part in parts:
            b = part.bbox()
            out.append([b.left / 1000, b.bottom / 1000, b.right / 1000, b.top / 1000])
    return sorted(out)


def main(gds, out):
    ly = db.Layout()
    ly.read(gds)
    top = ly.cell(TOP)

    def region(layer, datatype):
        return db.Region(top.begin_shapes_rec(ly.layer(layer, datatype)))

    activ, psd = region(1, 0), region(14, 0)
    nwell, macro = region(31, 0).merged(), region(25, 0).merged()
    ntap = ((activ - psd) & nwell).merged()
    substrate = (db.Region(nwell.bbox()) - nwell - macro).merged()

    spec = {
        "stackup": [{"name": "gatpoly", "layer": "5/0", "role": "gate", "active_layer": "1/0"}]
        + [{"name": n, "layer": f"{l}/0", "label_layer": f"{l}/25"} for n, l in METALS],
        "vias": [
            {"name": "cont", "layer": "6/0", "between": ["gatpoly", "metal1"]},
            {"name": "via1", "layer": "19/0", "between": ["metal1", "metal2"]},
            {"name": "via2", "layer": "29/0", "between": ["metal2", "metal3"]},
            {"name": "via3", "layer": "49/0", "between": ["metal3", "metal4"]},
        ],
        "nets": [
            {"name": "VPWR", "kind": "supply"},
            {"name": "VGND", "kind": "supply"},
            # Names the same two nets carry inside the standard cells and
            # the SRAM macro; PDN_MACRO_CONNECTIONS (src/config.json) joins
            # the macro's three pins to VPWR/VGND, DR 0005 for VDDARRAY!.
            {"name": "VDD", "kind": "supply", "same_net_as": "VPWR"},
            {"name": "VSS", "kind": "supply", "same_net_as": "VGND"},
            {"name": "VDD!", "kind": "supply", "same_net_as": "VPWR"},
            {"name": "VDDARRAY!", "kind": "supply", "same_net_as": "VPWR"},
            {"name": "VSS!", "kind": "supply", "same_net_as": "VGND"},
        ],
        "ties": [
            {"name": "nwell_tie", "well_layer": "31/0", "tap_layer": "1/0",
             "tap_boxes": boxes(ntap), "connect_to": "metal1", "net": "VPWR"},
            {"name": "substrate_tie", "well_layer": None, "well_boxes": boxes(substrate),
             "tap_layer": "1/0", "tap_requires": ["14/0"], "connect_to": "metal1",
             "net": "VGND"},
        ],
    }
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(spec, handle, indent=1)
        handle.write("\n")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
