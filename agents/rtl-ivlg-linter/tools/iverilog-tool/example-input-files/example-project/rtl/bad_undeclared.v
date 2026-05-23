// bad_undeclared.v — References an undeclared identifier (q_next).
// Expected: error/implicit-wire warning for q_next.
`timescale 1ns/1ps
`default_nettype none

module bad_undeclared (
    input  wire clk,
    input  wire rst_n,
    input  wire d,
    output reg  q
);

    // q_next is never declared — with `default_nettype none this is an error.
    always @(posedge clk) begin
        if (!rst_n) q <= 1'b0;
        else        q <= q_next;
    end

endmodule
