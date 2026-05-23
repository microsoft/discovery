// bad_syntax.v — Deliberate syntax errors for linter testing.
// Expected: parser errors (missing semicolon, missing endmodule).
`timescale 1ns/1ps

module bad_syntax (
    input  wire clk,
    input  wire rst_n,
    output reg  q
);

    // Missing semicolon after the assignment below
    always @(posedge clk) begin
        if (!rst_n)
            q <= 1'b0
        else
            q <= ~q;
    end

// Intentionally missing 'endmodule' to trigger a second parser error
