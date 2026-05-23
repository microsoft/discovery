# Example RTL project

A small, realistic Verilog project laid out the way an EDA engineer would
keep one. Mount this folder at `/project` inside the `iverilog` container
(or upload it as a tarball) and the agent will discover, lint, and
optionally simulate it.

## Layout

```
example-project/
├── Makefile          # `make lint`, `make sim`
├── filelist.f        # +incdir+ + source list (consumed by iverilog -f)
├── include/
│   └── defines.vh    # `WIDTH macro shared by good_alu.v
├── rtl/
│   ├── good_counter.v        # Clean 4-bit counter
│   ├── good_fsm.v            # Clean 3-state Moore FSM
│   ├── good_alu.v            # Clean 8-bit ALU (uses include/defines.vh)
│   ├── bad_syntax.v          # Missing ; and missing endmodule
│   ├── bad_undeclared.v      # References undeclared net q_next
│   ├── bad_width_mismatch.v  # 8-bit -> 4-bit truncation
│   └── bad_latch.v           # Inferred latch in always @*
└── tb/
    └── tb_counter.v          # Self-checking smoke testbench for good_counter
```

## Expected lint outcomes (agent E2E tests)

| File                    | Outcome                                                            |
|-------------------------|--------------------------------------------------------------------|
| `good_counter.v`        | clean                                                              |
| `good_fsm.v`            | clean                                                              |
| `good_alu.v`            | clean (with `+incdir+include`)                                     |
| `bad_syntax.v`          | parser error: missing `;`, missing `endmodule`                     |
| `bad_undeclared.v`      | error: `q_next` not declared (`default_nettype none`)              |
| `bad_width_mismatch.v`  | warning: implicit truncation 8→4                                   |
| `bad_latch.v`           | flagged by `check_inferred_latches()` (iverilog itself is silent)  |
