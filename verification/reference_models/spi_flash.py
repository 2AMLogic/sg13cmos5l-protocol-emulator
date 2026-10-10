"""Independent SPI-flash behavioural model (issue #140; DR 0013 layer 2).

A pure-Python model of a serial NOR flash as the Tiny Tapeout QSPI Pmod's
Winbond W25Q128JV presents itself in plain single-bit SPI: it answers the
`0x03` READ command from a byte image and checks the master's SPI **mode 0**
behaviour while it does. It is the SPI-flash half of DR 0013's verification
list ("a SPI flash behavioural model that answers `0x03` reads"), and it is
written to share no code with the boot program, the ISA core, the assembler
or `reference_models/spi.py` (which grades a controller *burst*; this model
plays the *device* and so has to react, not just judge).

Use
---
Feed it the three lines the flash sees at the instants they are known, in
time order::

    flash = SpiFlashModel(image)
    flash.step(t_ns, cs=1, sck=0, mosi=0)
    ...
    value = flash.miso(t_ns)      # 0, 1, or None when MISO is not driven

`step()` takes levels 0/1; any other value (None for x/z) is a violation.
`miso(t)` is what the flash drives at `t`: nothing (None, high impedance)
outside a data phase, and during one the bit selected by the last falling
edge, valid from `t_clqv_ns` after that edge. The model never reads MISO
back, so a bench that wants to know what the master *sampled* compares the
master's result with the image.

What it checks (each a string in `violations`; a clean run has none)
--------------------------------------------------------------------
* mode 0: SCK is low when CS falls, low when CS rises, and does not move
  while CS is high;
* CS setup before the first rising SCK edge (`t_css_ns`), CS hold after the
  last one (`t_csh_ns`), CS high time between transactions (`t_shsl_ns`);
* MOSI stable around every rising edge (`t_su_ns` before, `t_h_ns` after);
* SCK high and low pulse widths (`t_clh_ns`, `t_cll_ns`) and the 0x03 READ
  frequency ceiling (`f_max_hz`);
* the master leaves `t_clqv_ns` between a falling edge and the next rising
  edge, because that is when the flash's new MISO bit becomes valid: a
  rising edge earlier than that samples a bit that is not there yet;
* the command is `0x03` (anything else is reported and the flash then
  ignores the transaction, driving nothing).

What it records (`transactions`, one dict per CS assertion)
-----------------------------------------------------------
`opcode`, `address` (24 bits, or None if the transaction ended before it was
complete), `bits` (rising edges seen), `bytes_read` (whole data bytes
clocked out, and `data_bits` for the exact count), `t_cs_fall`, `t_cs_rise`.
A READ runs on from its address and wraps at the end of the image, as the
part does at the end of its array.

The default timing numbers are the W25Q128JV's as recalled by the author of
this file (3.0-3.6 V, READ 0x03 at 50 MHz); they were NOT re-read from the
datasheet when this model was written and must be checked against it before
anything is claimed about real silicon timing. The benches run the core at
a 10 ns period, so every one of them holds with at least one cycle of margin
whatever the exact figure is, and the numbers are constructor parameters.
They are limits the *master* must meet; this is a model of a conforming
slave, not a measurement of any part.
"""

READ = 0x03


class SpiFlashModel:
    def __init__(
        self,
        image,
        *,
        f_max_hz=50e6,
        t_css_ns=5.0,
        t_csh_ns=5.0,
        t_shsl_ns=10.0,
        t_su_ns=2.0,
        t_h_ns=3.0,
        t_clh_ns=4.5,
        t_cll_ns=4.5,
        t_clqv_ns=7.0,
    ):
        self.image = bytes(image)
        if not self.image:
            raise ValueError("a flash image needs at least one byte")
        self.f_max_hz = f_max_hz
        self.t_css_ns = t_css_ns
        self.t_csh_ns = t_csh_ns
        self.t_shsl_ns = t_shsl_ns
        self.t_su_ns = t_su_ns
        self.t_h_ns = t_h_ns
        self.t_clh_ns = t_clh_ns
        self.t_cll_ns = t_cll_ns
        self.t_clqv_ns = t_clqv_ns

        self.violations = []
        self.transactions = []
        self._cs = 1
        self._sck = 0
        self._mosi = 0
        self._started = False
        self._tx = None
        self._t_cs_rise = None
        self._t_mosi_change = None
        self._t_rise = None
        self._t_fall = None
        self._prev_rise = None
        self._miso_bit = None
        self._miso_prev = None
        self._miso_valid_at = None

    # ---- helpers -------------------------------------------------------

    def _violate(self, t, text):
        self.violations.append(f"t={t:.3f} ns: {text}")

    def _bit_to_present(self):
        """The data bit the next falling edge makes the flash present."""
        tx = self._tx
        index = (tx["address"] + tx["data_bits"] // 8) % len(self.image)
        return (self.image[index] >> (7 - tx["data_bits"] % 8)) & 1

    # ---- the pins ------------------------------------------------------

    def step(self, t, cs, sck, mosi):
        """The lines at time `t` (ns). Call it every time any line may have
        changed; calling it with nothing changed is harmless."""
        for name, value in (("CS", cs), ("SCK", sck), ("MOSI", mosi)):
            if value not in (0, 1):
                self._violate(t, f"{name} is {value!r}, not a logic level")
                return
        if not self._started:
            self._started = True
            self._cs, self._sck, self._mosi = cs, sck, mosi
            self._t_mosi_change = t
            if cs == 0:
                self._cs_fall(t, first=True)
            return

        # CS first, so a simultaneous CS and SCK change is judged against
        # the CS state the SCK edge belongs to.
        if cs != self._cs:
            if cs == 0:
                self._cs_fall(t)
            else:
                self._cs_rise(t)
            self._cs = cs
        if mosi != self._mosi:
            if (
                self._tx is not None
                and self._t_rise is not None
                and t - self._t_rise < self.t_h_ns
            ):
                self._violate(
                    t,
                    f"MOSI changed {t - self._t_rise:.3f} ns after a rising SCK edge "
                    f"(hold {self.t_h_ns} ns)",
                )
            self._mosi = mosi
            self._t_mosi_change = t
        if sck != self._sck:
            if self._cs == 1 and self._tx is None:
                self._violate(t, "SCK moved while CS is high")
                self._sck = sck
            elif sck == 1:
                self._rise(t)
                self._sck = 1
            else:
                self._fall(t)
                self._sck = 0

    def _cs_fall(self, t, first=False):
        if self._sck != 0:
            self._violate(t, "SCK is high when CS falls (mode 0 idles low)")
        if (
            self._t_cs_rise is not None
            and t - self._t_cs_rise < self.t_shsl_ns
        ):
            self._violate(
                t,
                f"CS was high for only {t - self._t_cs_rise:.3f} ns between "
                f"transactions (need {self.t_shsl_ns} ns)",
            )
        self._tx = {
            "opcode": None,
            "address": None,
            "bits": 0,
            "data_bits": 0,
            "bytes_read": 0,
            "t_cs_fall": t,
            "t_cs_rise": None,
            "_shift": 0,
            "_ignore": False,
        }
        self.transactions.append(self._tx)
        self._t_rise = None
        self._t_fall = None
        self._prev_rise = None
        self._miso_bit = None
        self._miso_prev = None

    def _cs_rise(self, t):
        tx = self._tx
        if tx is None:
            return
        if self._sck != 0:
            self._violate(t, "SCK is high when CS rises (mode 0 idles low)")
        if self._t_rise is not None and t - self._t_rise < self.t_csh_ns:
            self._violate(
                t,
                f"CS rose {t - self._t_rise:.3f} ns after the last rising SCK edge "
                f"(hold {self.t_csh_ns} ns)",
            )
        tx["t_cs_rise"] = t
        tx["bytes_read"] = tx["data_bits"] // 8
        self._tx = None
        self._t_cs_rise = t
        self._miso_bit = None
        self._miso_prev = None

    def _rise(self, t):
        tx = self._tx
        if tx is None:
            return
        if tx["bits"] == 0 and t - tx["t_cs_fall"] < self.t_css_ns:
            self._violate(
                t,
                f"first SCK edge {t - tx['t_cs_fall']:.3f} ns after CS fell "
                f"(setup {self.t_css_ns} ns)",
            )
        if self._t_fall is not None and t - self._t_fall < self.t_cll_ns:
            self._violate(t, f"SCK low for {t - self._t_fall:.3f} ns (min {self.t_cll_ns} ns)")
        if self._prev_rise is not None and t - self._prev_rise < 1e9 / self.f_max_hz - 1e-9:
            self._violate(
                t,
                f"SCK period {t - self._prev_rise:.3f} ns is above "
                f"{self.f_max_hz / 1e6:g} MHz",
            )
        if t - self._t_mosi_change < self.t_su_ns:
            self._violate(
                t,
                f"MOSI changed {t - self._t_mosi_change:.3f} ns before a rising SCK "
                f"edge (setup {self.t_su_ns} ns)",
            )
        if (
            self._miso_bit is not None
            and self._miso_valid_at is not None
            and t < self._miso_valid_at
        ):
            self._violate(
                t,
                f"rising SCK edge {t - self._t_fall:.3f} ns after the falling one: the "
                f"flash's bit is valid only after {self.t_clqv_ns} ns",
            )
        self._t_rise = t
        self._prev_rise = t
        tx["bits"] += 1
        if tx["_ignore"]:
            return
        n = tx["bits"]
        if n <= 8:
            tx["_shift"] = (tx["_shift"] << 1) | self._mosi
            if n == 8:
                tx["opcode"] = tx["_shift"]
                tx["_shift"] = 0
                if tx["opcode"] != READ:
                    tx["_ignore"] = True
                    self._violate(
                        t, f"command 0x{tx['opcode']:02x}: only READ (0x03) is modelled"
                    )
        elif n <= 32:
            tx["_shift"] = (tx["_shift"] << 1) | self._mosi
            if n == 32:
                tx["address"] = tx["_shift"]
        else:
            tx["data_bits"] += 1

    def _fall(self, t):
        tx = self._tx
        if tx is None:
            return
        if self._t_rise is not None and t - self._t_rise < self.t_clh_ns:
            self._violate(t, f"SCK high for {t - self._t_rise:.3f} ns (min {self.t_clh_ns} ns)")
        self._t_fall = t
        if tx["_ignore"] or tx["address"] is None or tx["bits"] < 32:
            self._miso_bit = None
            return
        # Data phase: the falling edge after rising edge 32 + k presents bit k.
        self._miso_prev = self._miso_bit
        self._miso_bit = self._bit_to_present()
        self._miso_valid_at = t + self.t_clqv_ns

    # ---- MISO ----------------------------------------------------------

    def miso(self, t):
        """What the flash drives on MISO at `t`: 0, 1, or None (not driving).
        A bit changes `t_clqv_ns` after the falling edge that selected it;
        until then the previous bit (or nothing) is still there. A bench that
        polls once per core clock, with a period above `t_clqv_ns`, never sees
        the old bit after a falling edge it has already polled past."""
        if self._miso_bit is None:
            return None
        if self._miso_valid_at is not None and t < self._miso_valid_at:
            return self._miso_prev
        return self._miso_bit
