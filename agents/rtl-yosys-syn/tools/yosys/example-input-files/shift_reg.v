// shift_reg.v -- 8-bit shift register with parallel load
// Example input for Yosys synthesis agent
module shift_reg (
    input  wire       clk,
    input  wire       rst,
    input  wire       load,
    input  wire       shift_en,
    input  wire       shift_in,
    input  wire [7:0] data_in,
    output wire       shift_out,
    output reg  [7:0] data_out
);

assign shift_out = data_out[7];

always @(posedge clk) begin
    if (rst)
        data_out <= 8'b0;
    else if (load)
        data_out <= data_in;
    else if (shift_en)
        data_out <= {data_out[6:0], shift_in};
end

endmodule
