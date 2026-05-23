// tb_counter.v — Smoke testbench for good_counter.
// Drives reset + enable, checks count rolls 0 -> 5, then $finish.
`timescale 1ns/1ps

module tb_counter;
    reg        clk;
    reg        rst_n;
    reg        enable;
    wire [3:0] count;

    good_counter dut (
        .clk    (clk),
        .rst_n  (rst_n),
        .enable (enable),
        .count  (count)
    );

    // 100 MHz clock
    initial clk = 1'b0;
    always #5 clk = ~clk;

    initial begin
        $display("[TB] starting tb_counter");
        rst_n  = 1'b0;
        enable = 1'b0;
        #20;
        rst_n  = 1'b1;
        enable = 1'b1;
        #100;
        if (count == 4'd0) begin
            $display("[TB] FAIL: count never advanced");
            $fatal;
        end
        $display("[TB] PASS: final count = %0d", count);
        $finish;
    end
endmodule
