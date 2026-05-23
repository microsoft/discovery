// bad_latch.v — Combinational always block with incomplete assignment -> inferred latch.
// Expected: custom check_inferred_latches() flags this file.
// iverilog itself may not warn; the agent's static rule checker must catch it.
`timescale 1ns/1ps

module bad_latch (
    input  wire       sel,
    input  wire [3:0] a,
    input  wire [3:0] b,
    output reg  [3:0] y
);

    // Missing 'else' branch — y holds its previous value when sel=0 -> inferred latch.
    always @(*) begin
        if (sel)
            y = a & b;
        // no else, no default assignment -> latch on y
    end

endmodule
