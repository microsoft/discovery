// good_alu.v — Clean 8-bit ALU with 4 ops.
// Expected lint result: 0 errors, 0 warnings.
`timescale 1ns/1ps
`include "defines.vh"

module good_alu (
    input  wire [`WIDTH-1:0] a,
    input  wire [`WIDTH-1:0] b,
    input  wire [1:0]        op,
    output reg  [`WIDTH-1:0] y,
    output reg               zero
);

    always @(*) begin
        case (op)
            2'b00:   y = a + b;
            2'b01:   y = a - b;
            2'b10:   y = a & b;
            2'b11:   y = a | b;
            default: y = {`WIDTH{1'b0}};
        endcase
        zero = (y == {`WIDTH{1'b0}});
    end

endmodule
