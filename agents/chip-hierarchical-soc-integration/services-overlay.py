import ast,hashlib,json
from pathlib import Path
patches=[{'path': '/app/run.py', 'function': '_authoritative_exit_code', 'before_sha256': 'b4c96ab2f862156493a9914248b8527ce14b07b26ace88c6ccd7130a597ee294', 'after': 'def _authoritative_exit_code(path=None):\n    # save_final_results writes common_design_envelope.json; older builds\n    # wrote final_results.json. Read whichever exists so the exit code\n    # reflects the REAL status (a missing file must never read as success).\n    _candidates = ([path] if path else\n                   ["/output/common_design_envelope.json", "/output/final_results.json"])\n    for _p in _candidates:\n        try:\n            with open(_p, encoding="utf-8") as stream:\n                result = json.load(stream)\n            code = 0 if (result.get("status") == "completed" and\n                         result.get("validation", {}).get("verdict") in\n                         ("pass", "pass_with_caveats", "review")) else 1\n            if code:\n                print("CDE_JSON=" + json.dumps(result, separators=(",", ":")), flush=True)\n            return code\n        except Exception:\n            continue\n    return 1'}]
for patch in patches:
 p=Path(patch['path']); source=p.read_text(); tree=ast.parse(source)
 n=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==patch['function'])
 old=ast.get_source_segment(source,n)
 if old==patch['after']: continue
 if hashlib.sha256(old.encode()).hexdigest()!=patch['before_sha256']: raise RuntimeError('qualification39 source precondition mismatch: '+patch['path']+':'+patch['function'])
 lines=source.splitlines(keepends=True)
 p.write_text(''.join(lines[:n.lineno-1])+patch['after']+'\n'+''.join(lines[n.end_lineno:]))
 print('QUALIFICATION39_PATCH='+patch['path']+':'+patch['function'],flush=True)
