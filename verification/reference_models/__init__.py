"""Independent protocol reference models for verification-plan.md section 4
(issue #25; target-spec rows 1, 10, 11, 12).

Each model is deliberately independent of this repo's RTL and firmware --
that is the section's whole requirement ("a model that does not share code
with this design's RTL or firmware, so it cannot silently encode the same
bug on both sides of the comparison").  The UART model encodes generic
8N1 asynchronous-serial practice (row 10's cited convention), the SPI
model encodes the Motorola/Freescale/NXP SPI Block Guide mode conventions
row 11 names, and the I2C model checks timing against NXP UM10204 Rev. 6
Table 10 directly (row 12) -- none of them against this repo's DR 0001
cycle-budget arithmetic.

``stimulus`` supplies the constrained-random generators (one seeded
``random.Random`` drives a whole run) and the deterministic negative
controls.  The suites in ``verification/test_protocol_models.py`` run this
package under `klt functional-verification` with the seed recorded in
``verification/request-protocol-models.json``.
"""
