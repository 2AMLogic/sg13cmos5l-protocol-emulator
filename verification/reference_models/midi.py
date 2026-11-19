"""MIDI 1.0 channel voice messages carried over the 31,250-baud 8N1 link.

Channels are zero-based on the wire. A note-on with zero velocity retains
its wire encoding (the musical interpretation is note-off).
"""

BAUD = 31_250
STATUS = {"note_off": 0x80, "note_on": 0x90, "control_change": 0xB0}


def encode(kind, channel, key, value):
    if not (0 <= channel < 16 and 0 <= key < 128 and 0 <= value < 128):
        raise ValueError("MIDI channel or data byte out of range")
    return bytes((STATUS[kind] | channel, key, value))


def decode(stream):
    """Yield complete (kind, channel, key/controller, value) messages."""
    kinds = {status >> 4: kind for kind, status in STATUS.items()}
    status = first = None
    for byte in stream:
        if byte >= 0xF8:
            continue  # System real-time may occur between any two bytes.
        if byte & 0x80:
            status = byte if byte >> 4 in kinds else None
            first = None
        elif status is not None:
            if first is None:
                first = byte
            else:
                yield kinds[status >> 4], status & 15, first, byte
                first = None
