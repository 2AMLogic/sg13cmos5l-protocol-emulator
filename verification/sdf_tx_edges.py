"""Pure helper for `sdf_protocol_uart_tx` (issue #531): the TX pin's own
level changes out of the monitor's whole-`uo_out` transition list.

Kept free of cocotb so a plain unittest can cover it."""


def tx_level_changes(transitions, initial):
    """`(t_ps, level)` for each *change* of `uo_out[0]`.

    `transitions` is the monitor's retained event list (dicts with `pin`,
    `t_ps`, `value` -- `value` is the whole vector MSB first, so the last
    character is bit 0); `initial` is the settled TX level before the first
    event. An `uo_out` event that leaves bit 0 where it was (another output
    bit moved while TX held its level) is dropped, so the decoder's input
    and the published edge list derive from the same bit-0 changes.
    """
    changes = []
    level = initial
    for event in transitions:
        if event["pin"] != "uo_out":
            continue
        bit = event["value"][-1]
        assert bit in "01", f"uo_out reads {event['value']!r}; the TX measurement needs 0/1 pins"
        bit = int(bit)
        if bit == level:
            continue
        level = bit
        changes.append((event["t_ps"], bit))
    return changes
