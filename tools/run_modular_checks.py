"""Execute visible modular notebooks, retaining failures and final cleanup cells."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import nbformat
from nbclient import NotebookClient

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--live',action='store_true')
parser.add_argument('--isolated',action='store_true')
parser.add_argument('--notebook',choices=['modular_dac_acceptance.ipynb','unit2_dac5_acceptance.ipynb','safe_zero_rate_acceptance.ipynb'],help='Select a visible live acceptance notebook')
args=parser.parse_args()
if args.notebook and not args.live:parser.error('--notebook requires --live')
root=Path(__file__).resolve().parents[2]
name=(args.notebook or 'modular_dac_acceptance.ipynb') if args.live else 'multidac_offline_tests.ipynb'
n=nbformat.read(root/'malab/notebooks'/name,as_version=4)
out=root/'malab/notebooks/results'/('modular_run_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
out.mkdir(parents=True)
for c in n.cells:
    if c.cell_type=='code' and c.source.startswith('RUN_LIVE'):
        c.source=c.source.replace('RUN_LIVE=False',f'RUN_LIVE={args.live}').replace('ALL_OUTPUTS_ISOLATED=False',f'ALL_OUTPUTS_ISOLATED={args.isolated}')
def announce(cell,cell_index):
    if cell.cell_type=='code':print('RUN',cell.metadata.get('case_id',cell_index),flush=True)
client=NotebookClient(n,timeout=180,allow_errors=True,resources={'metadata':{'path':str(root)}},on_cell_start=announce)
km=client.create_kernel_manager();km.kernel_spec.argv=[sys.executable,'-m','ipykernel_launcher','-f','{connection_file}']
results=[]
try:client.execute()
finally:
    nbformat.write(n,out/'executed.ipynb')
    for i,c in enumerate(n.cells):
        if c.cell_type!='code' or c.execution_count is None:continue
        errors=[o for o in c.outputs if o.output_type=='error']
        results.append(dict(case=c.metadata.get('case_id',i),result='FAIL' if errors else 'PASS',errors=[e.evalue for e in errors]))
        for output in c.outputs:
            if output.output_type=='stream':print(output.text,flush=True)
        print(results[-1],flush=True)
    (out/'manifest.json').write_text(json.dumps(dict(notebook=name,results=results),indent=2),encoding='utf-8')
    print('Executed notebook:',out,flush=True)
sys.exit(int(any(r['result']=='FAIL' for r in results)))
