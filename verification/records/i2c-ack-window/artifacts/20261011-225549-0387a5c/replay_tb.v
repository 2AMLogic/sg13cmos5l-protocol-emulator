`timescale 1ns/1ps
// Replay testbench: drives formal_top_i2c_ack with the (ack_raw, ui_in) of an
// ABC counterexample, one word per clock; assertion failures are printed by
// Icarus as "ERROR: <file>:<line>" with the failing time.
module replay_tb;
  reg clk = 1'b0;
  reg [7:0] ui_in = 8'h00;
  reg ack_raw = 1'b0;
  reg [8:0] stim [0:`NFRAMES-1];
  integer cyc = 0;
  formal_top_i2c_ack dut (.clk(clk), .ui_in(ui_in), .ack_raw(ack_raw));
  initial begin
    $readmemh(`STIM, stim);
    {ack_raw, ui_in} = stim[0];
    $dumpfile(`VCD);
    $dumpvars(0, replay_tb);
  end
  always #5 clk = ~clk;
  always @(negedge clk) begin
    cyc <= cyc + 1;
    if (cyc + 1 >= `NFRAMES) $finish;
    {ack_raw, ui_in} <= stim[cyc + 1];
  end
endmodule
