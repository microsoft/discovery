#!/usr/bin/env python3
"""Run one script in an isolated workspace; preserve logs/artifacts even on failure."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def copy_artifacts(work, output):
    """Copy nested regular files, excluding scratch and symlink traversal."""
    for source in work.rglob('*'):
        relative = source.relative_to(work)
        if 'scratch' in relative.parts or any(parent.is_symlink() for parent in
                                               [source, *source.parents]):
            continue
        if source.is_file():
            # Keep the launcher transcript intact if the script also writes logs.out.
            target = output / ('script-logs.out' if relative == Path('logs.out') else relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('script_path', type=Path)
    parser.add_argument('output_dir', type=Path)
    args = parser.parse_args(argv)
    script = args.script_path.resolve(strict=True)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='psi4-job-', dir=output.parent) as directory:
        root = Path(directory)
        work, scratch = root / 'work', root / 'scratch'
        work.mkdir()
        scratch.mkdir()
        # Preflight write permissions before importing Psi4 in the child process.
        for folder in (work, scratch):
            probe = folder / '.write-probe'
            probe.write_bytes(b'psi4')
            probe.unlink()
        env = dict(os.environ, PSI4_WORK_DIR=str(work), PSI4_OUTPUT_DIR=str(output),
                   PSI_SCRATCH=str(scratch),
                   TMPDIR=str(scratch), TEMP=str(scratch), TMP=str(scratch),
                   PYTHONUNBUFFERED='1')
        exit_code = 1
        failure = None
        with (output / 'logs.out').open('w', encoding='utf-8') as log:
            try:
                process = subprocess.Popen(
                    [sys.executable, str(script)], cwd=work, env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', errors='replace', bufsize=1)
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    sys.stdout.write(line)
                    sys.stdout.flush()
                process.stdout.close()
                exit_code = process.wait()
            except OSError as error:
                failure = str(error)
                log.write(f'Launcher failed: {error}\n')
            finally:
                try:
                    copy_artifacts(work, output)
                except (OSError, shutil.Error) as error:
                    failure = f'Artifact copy failed: {error}'
                    print(failure, file=sys.stderr)
                    if exit_code == 0:
                        exit_code = 1
        if exit_code != 0 or failure:
            (output / 'launcher_failure.json').write_text(json.dumps({
                'status': 'failed', 'exit_code': exit_code, 'error': failure,
            }, indent=2), encoding='utf-8')
        return exit_code


if __name__ == '__main__':
    sys.exit(main())
