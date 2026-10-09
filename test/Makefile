# Makefile
# See https://docs.cocotb.org/en/stable/quickstart.html for more info

# defaults
SIM ?= icarus
FST ?= -fst # Use more efficient FST format
TOPLEVEL_LANG ?= verilog
SRC_DIR = $(PWD)/../src
PROJECT_SOURCES = tt_um_2amlogic_protocol_emulator.v protocol_core.v protocol_program_memory.v protocol_boot_rom.v

# Behavioural model of the RM_IHPSG13_1P_256x16_c2_bm_bist SRAM macro the
# program memory is built on (spec/decision-records/0005-...). Vendored
# from the PDK -- see rtl/vendor/README.md for provenance and for why it
# is NOT in info.yaml's source_files (the macro is a hard block: LibreLane
# blackboxes it against the LEF/liberty wired up in src/config.json; only
# simulation needs a model). Needed by BOTH legs below: the RTL leg
# elaborates it in place of the macro, and the gate-level leg needs it
# because the post-synthesis netlist instantiates the macro by name and
# the stdcell model library does not contain it.
SRAM_DIR = $(PWD)/../rtl/vendor
SRAM_MODELS = RM_IHPSG13_1P_256x16_c2_bm_bist.v RM_IHPSG13_1P_core_behavioral_bm_bist.v

ifneq ($(GATES),yes)

# RTL simulation:
SIM_BUILD				= sim_build/rtl
# The macro model's `FUNCTIONAL` branch is the plain behavioural instance;
# without the define it elaborates a `specify` block of timing checks that
# only an SDF-annotated run wants (rtl/vendor/README.md).
COMPILE_ARGS    += -DFUNCTIONAL
VERILOG_SOURCES += $(addprefix $(SRAM_DIR)/,$(SRAM_MODELS))
VERILOG_SOURCES += $(addprefix $(SRC_DIR)/,$(PROJECT_SOURCES))

else

# Gate level simulation:
SIM_BUILD				= sim_build/gl
COMPILE_ARGS    += -DGL_TEST
COMPILE_ARGS    += -DFUNCTIONAL
COMPILE_ARGS    += -DSIM
VERILOG_SOURCES += $(PDK_ROOT)/ihp-sg13cmos5l/libs.ref/sg13cmos5l_io/verilog/sg13cmos5l_io.v
VERILOG_SOURCES += $(PDK_ROOT)/ihp-sg13cmos5l/libs.ref/sg13cmos5l_stdcell/verilog/sg13cmos5l_stdcell.v
VERILOG_SOURCES += $(PDK_ROOT)/ihp-sg13cmos5l/libs.ref/sg13cmos5l_stdcell/verilog/sg13cmos5l_udp.v
VERILOG_SOURCES += $(addprefix $(SRAM_DIR)/,$(SRAM_MODELS))

# this gets copied in by the GDS action workflow. GATE_LEVEL_NETLIST may be
# overridden on the command line (flow/run-firmware-gate-level.sh, issue #108,
# points it at a frozen LibreLane netlist instead of copying a file in).
GATE_LEVEL_NETLIST ?= $(PWD)/gate_level_netlist.v
VERILOG_SOURCES += $(GATE_LEVEL_NETLIST)

endif

# Allow sharing configuration between design and testbench via `include`:
COMPILE_ARGS 		+= -I$(SRC_DIR)

# Include the testbench sources:
VERILOG_SOURCES += $(PWD)/tb.v
TOPLEVEL = tb

# List test modules to run, separated by commas and without the .py suffix:
COCOTB_TEST_MODULES = test

# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim
