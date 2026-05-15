module ClockResetController (
    input wire clk,       // Clock input
    input wire rst_n,     // Active-low reset input
    output reg reset_out  // Synchronized reset output
);

    reg [1:0] reset_sync; // Synchronizer registers

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            reset_sync <= 2'b00; // Reset synchronizer
            reset_out <= 1'b1;   // Assert reset
        end else begin
            reset_sync <= {reset_sync[0], 1'b1}; // Shift in '1'
            reset_out <= ~reset_sync[1];        // Deassert reset after synchronization
        end
    end

endmodule
