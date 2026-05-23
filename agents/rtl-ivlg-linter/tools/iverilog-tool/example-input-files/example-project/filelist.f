// filelist.f — iverilog file list for the clean RTL portion of the example project.
// Used by `iverilog -f filelist.f` to compile/lint the good design + testbench.
+incdir+./include
./rtl/good_counter.v
./rtl/good_fsm.v
./rtl/good_alu.v
./tb/tb_counter.v
