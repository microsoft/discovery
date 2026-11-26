import os
import runpy

os.environ["TMPDIR"] = "/workdir"
runpy.run_path("/app/run.py", run_name="__main__")
