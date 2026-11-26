#!/usr/bin/env python3
"""
rtl_frontend.py -- shared multi-language RTL frontend helper for the chip-* tools.

Verilog is the default. This module makes VHDL (and mixed VHDL+Verilog) a
first-class, supported corner case without changing behavior for Verilog-only
callers.

Two consumer classes:

  * Yosys-based tools (rtl-design, cdc-rdc-signoff, lec, logic-synthesis):
    use `yosys_read_block(files, top, params)` to emit the Yosys read-in
    commands. Verilog/SystemVerilog sources use `read_verilog`; VHDL sources use
    the GHDL Yosys frontend, which is NOT auto-loaded -- so the block loads the
    plugin explicitly (`plugin -i ghdl`) and elaborates the top with `ghdl`.
    This requires a base image that ships the ghdl-yosys-plugin (e.g.
    `ghdl/synth:beta`); Debian's apt `ghdl` (mcode) does NOT provide it.

  * Simulator tools (functional-verification, code/functional coverage):
    Icarus/Verilator cannot read VHDL. Use `ghdl_synth_to_verilog_cmd(...)` to
    lower a VHDL/mixed design to a single synthesizable Verilog file the existing
    Verilog sim/coverage path can consume, or `detect_language(...)` to branch.

The canonical copy lives at catalog/tools/rtl_frontend.py; each tool vendors a
copy into its own build context (COPYed by its Containerfile). Keep the copies
in sync.
"""

VHDL_EXTS = (".vhd", ".vhdl")
VERILOG_EXTS = (".v", ".sv", ".svh", ".vh", ".verilog")


def is_vhdl(path):
    """True if *path* looks like a VHDL source by extension."""
    return str(path).lower().endswith(VHDL_EXTS)


def detect_language(files):
    """Classify a source set as 'verilog' (default), 'vhdl', or 'mixed'.

    An empty set is treated as 'verilog' so Verilog-only callers are unchanged.
    """
    has_vhdl = any(is_vhdl(f) for f in files)
    has_verilog = any(not is_vhdl(f) for f in files)
    if has_vhdl and has_verilog:
        return "mixed"
    if has_vhdl:
        return "vhdl"
    return "verilog"


def _vhdl_std(params):
    params = params or {}
    # Accept either `vhdl_std` or `std`; default to VHDL-2008.
    std = str(params.get("vhdl_std", params.get("std", "08"))).strip() or "08"
    return std


def yosys_read_block(files, top, params=None):
    """Build the Yosys read-in commands for a mixed Verilog/VHDL source set.

    Verilog/SystemVerilog sources use `read_verilog -sv`. The `-sv` flag is
    required, not optional: Yosys defaults to Verilog-2005, so a bare
    `read_verilog` cannot parse SystemVerilog constructs such as `always_comb`
    and aborts elaboration before any analysis runs. This matches the sibling
    formal path, which already reads with `-sv`. VHDL sources load the GHDL
    plugin (`plugin -i ghdl`) then elaborate the top (`ghdl --std=NN <files> -e
    <top>`). Verilog is read first so a VHDL top may instantiate Verilog
    blackboxes.
    """
    params = params or {}
    vhdl = [f for f in files if is_vhdl(f)]
    verilog = [f for f in files if not is_vhdl(f)]
    lines = []
    for f in verilog:
        lines.append("read_verilog -sv {}".format(f))
    if vhdl:
        std = _vhdl_std(params)
        # The GHDL frontend is not auto-loaded; a bare `ghdl` command fails
        # ("No such command: ghdl") unless the plugin is loaded explicitly.
        lines.append("plugin -i ghdl")
        lines.append("ghdl --std={} ".format(std) + " ".join(vhdl) + " -e {}".format(top))
    return "\n".join(lines)


def ghdl_synth_to_verilog_cmd(files, top, out_verilog, params=None):
    """Return an argv that lowers a VHDL/mixed design to one Verilog file.

    Uses `ghdl synth --out=verilog` (available in the ghdl-yosys-plugin image) so
    the Icarus/Verilator sim + coverage path can consume a VHDL design. Verilog
    sources in a mixed set are passed through GHDL's Verilog import where
    supported; callers with pure-Verilog input should skip this and use the
    native flow. Only VHDL files are handed to `ghdl synth`.
    """
    std = _vhdl_std(params)
    vhdl = [f for f in files if is_vhdl(f)]
    argv = ["ghdl", "synth", "--std={}".format(std), "--out=verilog"] + vhdl + ["-e", top]
    return argv, out_verilog


def language_note(files):
    """Human-readable one-liner recording the detected language + file counts."""
    lang = detect_language(files)
    nv = sum(1 for f in files if not is_vhdl(f))
    nh = sum(1 for f in files if is_vhdl(f))
    return "rtl_language={} (verilog_files={}, vhdl_files={})".format(lang, nv, nh)
