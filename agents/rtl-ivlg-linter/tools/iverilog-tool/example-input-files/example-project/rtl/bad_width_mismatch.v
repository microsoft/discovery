// bad_width_mismatch.v — Assigns 8-bit value to 4-bit register; truncation warning expected.
// Expected: width-mismatch / implicit-truncation warning.
`timescale 1ns/1ps

module bad_width_mismatch (
    input  wire [7:0] big_in,
    output reg  [3:0] small_out
);

    always @(*) begin
        // 8-bit -> 4-bit assignment (silent truncation of upper 4 bits)
        small_out = big_in;
    end

endmodule
