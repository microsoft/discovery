// good_fsm.v — Clean 3-state Moore FSM (IDLE -> WORK -> DONE -> IDLE).
// Expected lint result: 0 errors, 0 warnings.
`timescale 1ns/1ps

module good_fsm (
    input  wire clk,
    input  wire rst_n,
    input  wire start,
    input  wire done_in,
    output reg  busy,
    output reg  done
);

    localparam [1:0] S_IDLE = 2'd0,
                     S_WORK = 2'd1,
                     S_DONE = 2'd2;

    reg [1:0] state, next_state;

    // Sequential: state register
    always @(posedge clk) begin
        if (!rst_n) state <= S_IDLE;
        else        state <= next_state;
    end

    // Combinational: next-state logic — fully specified, no latch risk
    always @(*) begin
        next_state = state;
        case (state)
            S_IDLE: if (start)   next_state = S_WORK;
            S_WORK: if (done_in) next_state = S_DONE;
            S_DONE:              next_state = S_IDLE;
            default:             next_state = S_IDLE;
        endcase
    end

    // Combinational: outputs — fully specified
    always @(*) begin
        busy = 1'b0;
        done = 1'b0;
        case (state)
            S_IDLE: begin busy = 1'b0; done = 1'b0; end
            S_WORK: begin busy = 1'b1; done = 1'b0; end
            S_DONE: begin busy = 1'b0; done = 1'b1; end
            default: begin busy = 1'b0; done = 1'b0; end
        endcase
    end

endmodule
