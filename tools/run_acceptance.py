"""Execute selected visible notebook cases, retaining outputs and failures."""
import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback


def execute_jupyter(notebook, args, manifest, output_dir, repo):
    """Use a real Jupyter kernel from this Python environment (optional dependency)."""
    import nbformat
    from nbclient import NotebookClient
    selected = nbformat.reads(json.dumps(notebook), as_version=4)
    selected.cells = [c for c in selected.cells if c.cell_type != 'code'
                      or c.metadata.get('case_id') in args.cases
                      or 'setup' in c.metadata.get('tags', [])]
    for cell in selected.cells:
        if cell.cell_type != 'code':
            continue
        cell.outputs = []
        cell.execution_count = None
        if cell.id == 'imports':
            cell.source = f"RUN_ID = {manifest['run_id']!r}\n" + cell.source
        if 'parameters' in cell.metadata.get('tags', []):
            cell.source += f"\nRUN_LIVE = {args.live!r}\nALL_OUTPUTS_ISOLATED = {args.isolated!r}\n"
    nbformat.validate(selected)
    def announce(cell, cell_index):
        if cell.cell_type == 'code':
            print('RUN Jupyter', cell.metadata.get('case_id', cell.id), flush=True)
    client = NotebookClient(selected, timeout=420, allow_errors=False,
                            resources={'metadata': {'path': str(repo.parent)}},
                            on_cell_start=announce)
    manager = client.create_kernel_manager()
    manager.kernel_spec.argv = [sys.executable, '-m', 'ipykernel_launcher', '-f', '{connection_file}']
    failed = False
    try:
        client.execute()
    except Exception:
        failed = True
        traceback.print_exc()
    finally:
        for cell in selected.cells:
            if cell.cell_type != 'code' or cell.execution_count is None:
                continue
            errors = [o for o in cell.outputs if o.output_type == 'error']
            case = cell.metadata.get('case_id', cell.id)
            manifest['results'].append(dict(case=case, result='FAIL' if errors else 'PASS',
                error=errors[0].get('evalue') if errors else None))
            print(manifest['results'][-1], flush=True)
        manifest['engine'] = 'Jupyter/nbclient'
        manifest['kernel_python'] = sys.executable
        nbformat.write(selected, output_dir/'executed.ipynb')
        (output_dir/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
        print('Run evidence:', output_dir, flush=True)
    return int(failed)


class Tee(io.StringIO):
    def __init__(self, terminal):
        super().__init__()
        self.terminal = terminal
    def write(self, text):
        self.terminal.write(text)
        self.terminal.flush()
        return super().write(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', nargs='+', required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--isolated', action='store_true')
    parser.add_argument('--jupyter', action='store_true', help='Execute with a real Jupyter kernel in this environment')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    os.chdir(repo.parent)
    source = repo/'notebooks/live_acceptance.ipynb'
    raw = source.read_bytes()
    notebook = json.loads(raw)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output_dir = repo/'notebooks/results'/run_id
    output_dir.mkdir(parents=True)
    names = {c.get('metadata', {}).get('case_id') for c in notebook['cells']}
    if set(args.cases)-names:
        parser.error('Unknown cases: ' + ','.join(set(args.cases)-names))
    ns = {'__name__': '__main__', 'RUN_ID': run_id}
    manifest = dict(run_id=run_id, notebook_sha256=hashlib.sha256(raw).hexdigest(),
                    cases=args.cases, live=args.live, isolated=args.isolated, results=[], revisions={})
    for directory in (repo, repo.parent):
        git=['git','-c',f'safe.directory={directory.as_posix()}','-C',str(directory)]
        manifest['revisions'][directory.name] = dict(
            head=subprocess.check_output(git+['rev-parse','HEAD'],text=True).strip(),
            dirty=bool(subprocess.check_output(git+['status','--porcelain'],text=True).strip()))
    if args.jupyter:
        return execute_jupyter(notebook, args, manifest, output_dir, repo)
    count = 0
    failed = False
    try:
        for cell in notebook['cells']:
            meta=cell.get('metadata', {})
            case=meta.get('case_id')
            if cell['cell_type']!='code' or (case not in args.cases and 'setup' not in meta.get('tags', [])):
                continue
            count+=1
            cell['execution_count']=count
            cell['outputs']=[]
            output=Tee(sys.stdout)
            error=None
            print('RUN',case or cell['id'],flush=True)
            try:
                with contextlib.redirect_stdout(output):
                    exec(compile(''.join(cell['source']),f'{source}:{cell["id"]}','exec'),ns)
                if 'parameters' in meta.get('tags', []):
                    ns['RUN_LIVE']=args.live
                    ns['ALL_OUTPUTS_ISOLATED']=args.isolated
            except Exception as exc:
                error=dict(output_type='error',ename=type(exc).__name__,evalue=str(exc),
                           traceback=traceback.format_exc().splitlines())
                failed=True
                traceback.print_exc()
            if output.getvalue():
                cell['outputs'].append(dict(output_type='stream',name='stdout',text=output.getvalue()))
            if error:
                cell['outputs'].append(error)
            manifest['results'].append(dict(case=case or cell['id'],result='FAIL' if error else 'PASS',
                                            error=error['evalue'] if error else None))
            if error and not case:
                break
    finally:
        (output_dir/'executed.ipynb').write_text(json.dumps(notebook,indent=1)+'\n',encoding='utf-8')
        (output_dir/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
        print('Run evidence:',output_dir,flush=True)
    return int(failed)


if __name__=='__main__':
    raise SystemExit(main())
