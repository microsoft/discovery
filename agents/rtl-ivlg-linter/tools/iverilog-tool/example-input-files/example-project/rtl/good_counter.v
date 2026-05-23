// good_counter.v — Clean 4-bit synchronous up-counter with sync reset.
// Expected lint result: 0 errors, 0 warnings.
`timescale 1ns/1ps

module good_counter (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       enable,
    output reg  [3:0] count
);

    always @(posedge clk) begin
        if (!rst_n) begin
            count <= 4'b0000;
        end else if (enable) begin
            count <= count + 4'b0001;
        end
    end

endmodule
