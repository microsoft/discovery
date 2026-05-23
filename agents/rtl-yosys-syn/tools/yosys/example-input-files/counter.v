// counter.v -- Simple 16-bit up-counter with synchronous reset
// Example input for Yosys synthesis agent
module counter (
    input  wire        clk,
    input  wire        rst,
    input  wire        en,
    output reg  [15:0] count
);

always @(posedge clk) begin
    if (rst)
        count <= 16'b0;
    else if (en)
        count <= count + 16'b1;
end

endmodule
