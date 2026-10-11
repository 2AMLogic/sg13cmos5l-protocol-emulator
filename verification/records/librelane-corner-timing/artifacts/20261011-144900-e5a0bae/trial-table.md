| Trial | Design | gds run | Change from main's `src/config.json` | Worst setup, slow / typ / fast (ns) | Worst hold (ns) | Max-slew | Max-cap | Std-cell area (um^2) | Cells + macro / core |
|---|---|---|---|---|---|---|---|---|---|
| main | main (pre-#244) | 38108543866 | none (the run #246 was filed from) | +1.925 / +8.796 / +11.109 | +0.667 / +0.325 / +0.129 | 2 / 0 / 0 | 0 / 0 / 0 | 44,964.5 | 57.70 % |
| t24 | main (pre-#244) | 38131966596 | RUN_POST_GRT_DESIGN_REPAIR 1 | +1.887 / +8.789 / +11.095 | +0.664 / +0.321 / +0.130 | 2 / 0 / 0 | 0 / 0 / 0 | 44,948.1 | 57.68 % |
| t25 | main (pre-#244) | 38131969264 | post-GRT repair + resizer, PL and GRT setup margins 8 | +5.778 / +10.819 / +11.138 | +0.639 / +0.313 / +0.120 | 5 / 0 / 0 | 1 / 1 / 1 | 45,472.5 | 58.10 % |
| t26 | main (pre-#244) | 38133391079 | t25 + slew and cap repair margins 40 % (post-GPL and post-GRT) | +5.778 / +10.819 / +11.138 | +0.639 / +0.313 / +0.120 | 5 / 0 / 0 | 1 / 1 / 1 | 45,472.5 | 58.10 % |
| t27 | main (pre-#244) | 38133392956 | t25 + RSZ_CORNERS slow, typ, fast | +5.778 / +10.819 / +11.138 | +0.639 / +0.313 / +0.120 | 5 / 0 / 0 | 1 / 1 / 1 | 45,472.5 | 58.10 % |
| t34 | main (pre-#244) | 38135058264 | post-GRT resizer only (no post-GRT design repair), margins 8 | +5.996 / +10.807 / +11.130 | +0.639 / +0.313 / +0.119 | 2 / 0 / 0 | 0 / 0 / 0 | 45,468.9 | 58.09 % |
| t30 | main (pre-#244) | 38135049645 | t25 + GRT_DESIGN_REPAIR_MAX_WIRE_LENGTH 300 (the final config) | +6.565 / +10.772 / +11.109 | +0.573 / +0.265 / +0.089 | 0 / 0 / 0 | 2 / 2 / 2 | 46,194.6 | 58.67 % |
| t33 | main (pre-#244) | 38135055914 | t25 + GRT_DESIGN_REPAIR_MAX_WIRE_LENGTH 150 | +6.867 / +10.694 / +11.061 | +0.570 / +0.264 / +0.087 | 0 / 0 / 0 | 0 / 0 / 0 | 48,099.7 | 60.17 % |
| t0 | #244 top | 38124425108 | none | +3.716 / +9.926 / +11.070 | +0.666 / +0.323 / +0.130 | 0 / 0 / 0 | 0 / 0 / 0 | 45,251.1 | 57.92 % |
| t5 | #244 top | 38124446324 | SYNTH_SIZING 1 | +3.716 / +9.926 / +11.070 | +0.666 / +0.323 / +0.130 | 0 / 0 / 0 | 0 / 0 / 0 | 45,251.1 | 57.92 % |
| t7 | #244 top | 38124451107 | PL_RESIZER_SETUP_SLACK_MARGIN 4 | +3.716 / +9.926 / +11.070 | +0.666 / +0.323 / +0.130 | 0 / 0 / 0 | 0 / 0 / 0 | 45,251.1 | 57.92 % |
| t11 | #244 top | 38127917674 | PL_RESIZER_SETUP_SLACK_MARGIN 8 | +5.309 / +10.713 / +11.073 | +0.652 / +0.317 / +0.124 | 0 / 0 / 0 | 0 / 0 / 0 | 45,325.5 | 57.98 % |
| t6 | #244 top | 38124449056 | MAX_TRANSITION_CONSTRAINT 1.0 | +3.928 / +10.096 / +11.064 | +0.691 / +0.333 / +0.135 | 64 / 0 / 0 | 0 / 0 / 0 | 45,287.4 | 57.95 % |
| t1 | #244 top | 38124436483 | post-GRT repair + resizer, template margins | +4.258 / +10.313 / +11.048 | +0.664 / +0.319 / +0.125 | 0 / 0 / 0 | 0 / 0 / 0 | 45,262.0 | 57.93 % |
| t2 | #244 top | 38124438959 | post-GRT repair + resizer, margins 4 | +4.258 / +10.313 / +11.048 | +0.664 / +0.319 / +0.125 | 0 / 0 / 0 | 0 / 0 / 0 | 45,262.0 | 57.93 % |
| t22 | #244 top | 38129405884 | post-GRT repair + resizer, margins 6 | +4.258 / +10.313 / +11.048 | +0.664 / +0.319 / +0.125 | 0 / 0 / 0 | 0 / 0 / 0 | 45,262.0 | 57.93 % |
| t9 | #244 top | 38127913495 | post-GRT repair + resizer, margins 8 | +5.920 / +10.704 / +11.067 | +0.635 / +0.306 / +0.118 | 0 / 0 / 0 | 0 / 0 / 0 | 45,508.8 | 58.13 % |
| t23 | #244 top | 38131964648 | post-GRT repair + resizer, margins 9 | +7.289 / +10.712 / +11.073 | +0.663 / +0.322 / +0.129 | 0 / 0 / 0 | 0 / 0 / 0 | 46,308.9 | 58.76 % |
| t21 | #244 top | 38129404043 | post-GRT repair + resizer, margins 10 | +8.382 / +10.730 / +11.084 | +0.483 / +0.231 / +0.077 | 0 / 0 / 0 | 0 / 0 / 0 | 50,278.8 | 61.89 % |
| t28 | #244 top | 38133394998 | t9 + slew and cap repair margins 40 % (post-GPL and post-GRT) | +5.920 / +10.704 / +11.067 | +0.635 / +0.306 / +0.118 | 0 / 0 / 0 | 0 / 0 / 0 | 45,508.8 | 58.13 % |
| t29 | #244 top | 38133396810 | t9 + RSZ_CORNERS slow, typ, fast | +5.920 / +10.704 / +11.067 | +0.635 / +0.306 / +0.118 | 0 / 0 / 0 | 0 / 0 / 0 | 45,508.8 | 58.13 % |
| t32 | #244 top | 38135053878 | post-GRT resizer only (no post-GRT design repair), margins 8 | +6.374 / +10.743 / +11.093 | +0.642 / +0.310 / +0.120 | 0 / 0 / 0 | 0 / 0 / 0 | 45,548.7 | 58.16 % |
| t31 | #244 top | 38135051500 | t9 + GRT_DESIGN_REPAIR_MAX_WIRE_LENGTH 300 (the final config) | +5.785 / +10.714 / +11.074 | +0.560 / +0.261 / +0.083 | 0 / 0 / 0 | 0 / 0 / 0 | 46,047.7 | 58.55 % |
| t3 | #244 top | 38124441537 | PL_TIMING_DRIVEN 1 | +5.778 / +10.719 / +11.077 | +0.652 / +0.314 / +0.122 | 1 / 0 / 0 | 0 / 0 / 0 | 44,420.1 | 57.27 % |
| t12 | #244 top | 38127919533 | PL_TIMING_DRIVEN 1, PL margin 8 | +5.778 / +10.719 / +11.077 | +0.652 / +0.314 / +0.122 | 1 / 0 / 0 | 0 / 0 / 0 | 44,420.1 | 57.27 % |
| t14 | #244 top | 38127923704 | PL_TIMING_DRIVEN 1, RUN_POST_GRT_DESIGN_REPAIR 1 | +5.657 / +10.733 / +11.086 | +0.653 / +0.314 / +0.123 | 1 / 0 / 0 | 0 / 0 / 0 | 44,425.6 | 57.27 % |
| t16 | #244 top | 38129236778 | PL_TIMING_DRIVEN 1, DESIGN_REPAIR_MAX_WIRE_LENGTH 200 | +5.560 / +10.776 / +11.114 | +0.653 / +0.314 / +0.122 | 0 / 0 / 0 | 0 / 0 / 0 | 45,303.8 | 57.96 % |
| t13 | #244 top | 38127921256 | PL_TIMING_DRIVEN 1, DESIGN_REPAIR_MAX_WIRE_LENGTH 300 | +6.018 / +10.735 / +11.087 | +0.661 / +0.318 / +0.124 | 0 / 0 / 0 | 0 / 0 / 0 | 44,714.1 | 57.50 % |
| t17 | #244 top | 38129238657 | PL_TIMING_DRIVEN 1, DESIGN_REPAIR_MAX_WIRE_LENGTH 400 | +5.852 / +10.732 / +11.086 | +0.652 / +0.314 / +0.121 | 0 / 0 / 0 | 0 / 0 / 0 | 44,507.2 | 57.33 % |
| t10 | #244 top | 38127915568 | PL_TIMING_DRIVEN 1, post-GRT repair + resizer, margins 8 | +6.523 / +10.728 / +11.083 | +0.641 / +0.307 / +0.119 | 1 / 0 / 0 | 0 / 0 / 0 | 44,490.9 | 57.32 % |
| t15 | #244 top | 38129234907 | PL_TIMING_DRIVEN 1, max wire 300, post-GRT repair + resizer, GRT margin 8 | +6.512 / +10.698 / +11.064 | +0.655 / +0.316 / +0.122 | 0 / 0 / 0 | 0 / 0 / 0 | 44,766.7 | 57.54 % |
| t18 | #244 top | 38129321789 | PL_TIMING_DRIVEN 1, RSZ_DONT_TOUCH_RX on the 27 macro drive buffers | flow failed: post-CTS hold repair, RSZ-3009 insert_buffer failed on drvr_pin | | | | | |
| t19 | #244 top | 38129324759 | t18 + DESIGN_REPAIR_MAX_WIRE_LENGTH 300 | flow failed: post-CTS hold repair, RSZ-3009 insert_buffer failed on drvr_pin | | | | | |
| t20 | #244 top | 38129326490 | t18 + post-GRT repair + resizer, GRT margin 8 | flow failed: post-CTS hold repair, RSZ-3009 insert_buffer failed on drvr_pin | | | | | |
| t4 | #244 top | 38124443632 | SYNTH_STRATEGY DELAY 1 | flow failed after 4 h 16 min in the gds job: 40 Magic illegal-overlap errors, harden failed | | | | | |
