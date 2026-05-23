# Example-project Makefile — typical EDA-style targets exercised by the agent.
IVERILOG ?= iverilog
VVP      ?= vvp
STD      ?= 2012
TOP      ?= tb_counter
OUT      ?= sim/design.vvp

.PHONY: lint sim clean

lint:
	$(IVERILOG) -tnull -Wall -g$(STD) -f filelist.f

sim: $(OUT)
	$(VVP) $(OUT)

$(OUT): filelist.f
	mkdir -p sim
	$(IVERILOG) -o $(OUT) -s $(TOP) -g$(STD) -f filelist.f

clean:
	rm -rf sim lint_out
