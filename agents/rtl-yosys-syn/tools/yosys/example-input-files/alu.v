// alu.v -- Simple 8-bit ALU with 4 operations
// Example input for Yosys synthesis agent
module alu (
    input  wire [7:0] a,
    input  wire [7:0] b,
    input  wire [1:0] op,
    output reg  [7:0] result,
    output reg        zero
);

always @(*) begin
    case (op)
        2'b00: result = a + b;    // ADD
        2'b01: result = a - b;    // SUB
        2'b10: result = a & b;    // AND
        2'b11: result = a | b;    // OR
        default: result = 8'b0;
    endcase
    zero = (result == 8'b0);
end

endmodule
