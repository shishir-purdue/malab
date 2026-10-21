"""Loopback-only dashboard server, without third-party web dependencies."""
import argparse
import json
import secrets
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .controller import Dashboard
from malab.bench_config import dashboard_options, config_path
from malab.instruments.resistive_load import ResistorStore
from malab.instruments.channel_labels import LabelStore


class LocalServer(ThreadingHTTPServer):
    # Windows SO_REUSEADDR can permit two servers on the same address/port.
    # A single instrument owner and a single session token are required.
    allow_reuse_address=False
    def server_bind(self):
        if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()


def serve(dashboard,port=8765):
    token=secrets.token_urlsafe(32)
    static=Path(__file__).parent/'static'
    hosts={f'127.0.0.1:{port}',f'localhost:{port}'}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,status,body,kind='application/json'):
            if isinstance(body,dict):body=json.dumps(body,allow_nan=False).encode()
            elif isinstance(body,str):body=body.encode()
            self.send_response(status);self.send_header('Content-Type',kind+'; charset=utf-8')
            self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            try:self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):pass
        def allowed(self):return self.headers.get('Host') in hosts
        def do_GET(self):
            if not self.allowed():return self.send(403,{'error':'Local host only'})
            if self.path=='/api/state':return self.send(200,dashboard.snapshot())
            files={'/':('index.html','text/html'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css')}
            if self.path not in files:return self.send(404,{'error':'Not found'})
            filename,kind=files[self.path]
            self.send(200,(static/filename).read_text(encoding='utf-8').replace('__TOKEN__',token),kind)
        def do_POST(self):
            origin=self.headers.get('Origin')
            if (not self.allowed() or (origin and origin not in {'http://'+h for h in hosts})
                    or not secrets.compare_digest(self.headers.get('X-DAC-Token',''),token)):
                print('Rejected dashboard action: reload the page for this server session',flush=True)
                return self.send(403,{'error':'Local dashboard token required'})
            if self.path!='/api/action':return self.send(404,{'error':'Not found'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=8192 or self.headers.get('Content-Type','').split(';')[0]!='application/json':
                    raise ValueError('Expected a small JSON command')
                result=dashboard.submit(json.loads(self.rfile.read(size)))
                self.send(202,result)
            except (ValueError,TypeError) as exc:self.send(400,{'error':str(exc)})
    server=LocalServer(('127.0.0.1',port),Handler)
    dashboard.start()
    print(f'DAC dashboard ready at http://localhost:{port}',flush=True)
    try:server.serve_forever()
    finally:server.server_close();dashboard.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--config',type=Path,default=config_path())
    parser.add_argument('--dacs',nargs='+',help='Ordered unit IPs; overrides the config IP and USB lists')
    parser.add_argument('--dac',help='One-unit compatibility option')
    parser.add_argument('--meter');parser.add_argument('--meter-channel',type=int)
    parser.add_argument('--usbs',nargs='+',help='One USB port or none per unit, in the same order')
    parser.add_argument('--usb',help='One-unit USB compatibility option')
    parser.add_argument('--debug-stacks',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.debug_stacks:
        import faulthandler
        faulthandler.dump_traceback_later(10,repeat=True)
    config=dashboard_options(args.config)
    if args.dac and args.dacs:parser.error('Use --dac or --dacs, not both')
    if args.dacs or args.dac:
        config['addresses']=args.dacs or [args.dac]
        config['bench_ports']=[None]*len(config['addresses'])
    if args.usbs:config['bench_ports']=[None if p.lower()=='none' else p for p in args.usbs]
    if args.usb is not None:
        if args.usbs or len(config['addresses'])!=1:parser.error('--usb requires one unit; use --usbs for multiple units')
        config['bench_ports']=[args.usb or None]
    if args.meter:config['meter_address']=args.meter
    if args.meter_channel is not None:config['meter_channel']=args.meter_channel
    serve(Dashboard(**config,resistor_store=ResistorStore(args.config.parent/'resistors.local.json'),
                    label_store=LabelStore(args.config.parent/'labels.local.json')),args.port)
