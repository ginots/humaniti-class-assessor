"""Focused synthetic CPU/WASM startup diagnostic. Never calls assessment APIs."""
import hashlib
import argparse
import json
from pathlib import Path
import time
import urllib.request
from browser_check import Browser


class DiagnosticBrowser(Browser):
    def __init__(self):
        self.responses, self.failures, self.console, self.urls = [], [], [], {}
        super().__init__()
        self.call('Log.enable')

    def event(self, event):
        method, params = event.get('method'), event.get('params', {})
        session = event.get('sessionId', '')
        if method == 'Network.requestWillBeSent':
            self.urls[(session, params['requestId'])] = params['request']['url']
        elif method == 'Network.responseReceived':
            response = params['response']
            self.responses.append({'url':response['url'], 'status':response['status'], 'mime':response['mimeType'],
                                   'worker':bool(session),'disk_cache':response.get('fromDiskCache',False)})
        elif method == 'Network.loadingFailed':
            self.failures.append({'url':self.urls.get((session,params['requestId']),''),
                                  'error':params.get('errorText'),'blocked':params.get('blockedReason'),'worker':bool(session)})
        elif method == 'Runtime.exceptionThrown':
            detail=params['exceptionDetails']
            self.console.append({'type':'exception','description':detail.get('exception',{}).get('description',detail.get('text',''))[:2000],
                                 'url':detail.get('url'),'line':detail.get('lineNumber'),'worker':bool(session)})
        elif method == 'Runtime.consoleAPICalled' and params.get('type') in ('error','warning'):
            self.console.append({'type':params['type'],'messages':[str(a.get('value',a.get('description','')))[:1500] for a in params.get('args',[])], 'worker':bool(session)})
        elif method == 'Log.entryAdded' and params['entry'].get('level') in ('error','warning'):
            self.console.append({'type':'log','description':params['entry'].get('text','')[:2000],'url':params['entry'].get('url')})
        super().event(event)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--server-loss-pid',type=int,help='Only a diagnostic server PID owned by this test; stop it to verify outage handling.')
    args=parser.parse_args()
    browser=DiagnosticBrowser()
    browser.call('Page.addScriptToEvaluateOnNewDocument',{'source':"""
      window.__workerDiagnostics=[];
      const OriginalWorker=window.Worker;
      window.Worker=class extends OriginalWorker {
        constructor(...args){super(...args);this.addEventListener('error',e=>window.__workerDiagnostics.push({message:e.message,filename:e.filename,line:e.lineno,column:e.colno}));}
      };
    """})
    browser.call('Page.reload',{'ignoreCache':True})
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        if browser.js("!!document.getElementById('transcribe') && document.getElementById('health').textContent.includes('configured')"):
            break
        time.sleep(.1)
    print('CAPABILITIES',json.dumps(browser.js("({engine:document.getElementById('device').value,secure:isSecureContext,isolation:crossOriginIsolated,webcodecs:!!window.AudioDecoder})")),flush=True)
    browser.js("""(async()=>{
      const response=await fetch('/synthetic-test.mp4',{cache:'no-store'});
      const video=new DataTransfer();video.items.add(new File([await response.blob()],'synthetic.mp4',{type:'video/mp4'}));
      const vi=document.getElementById('video');vi.files=video.files;vi.dispatchEvent(new Event('change'));
      const captions=new DataTransfer();captions.items.add(new File(['WEBVTT\\n\\n00:00:00.000 --> 00:00:04.000\\nA synthetic caption for the independent VTT test.\\n'],'synthetic.vtt',{type:'text/vtt'}));
      const vt=document.getElementById('vtt');vt.files=captions.files;vt.dispatchEvent(new Event('change'));
      await new Promise(resolve=>setTimeout(resolve,200));
      document.getElementById('device').value='wasm';document.getElementById('transcribe').click();return true;
    })()""",True)
    deadline=time.monotonic()+150
    last=''
    while time.monotonic()<deadline:
        status=browser.js("document.getElementById('localStatus').textContent")
        if status!=last: print('STATUS',status,flush=True);last=status
        if status.startswith(('Local transcription complete:','Local transcription failed:','Transcription failed','Transcription worker','No usable speech')):break
        time.sleep(.5)
    print('WORKER_ERRORS',json.dumps(browser.js('window.__workerDiagnostics')),flush=True)
    print('CONSOLE',json.dumps(browser.console),flush=True)
    print('NETWORK_FAILURES',json.dumps(browser.failures),flush=True)
    print('ASSET_RESPONSES',json.dumps([r for r in browser.responses if any(s in r['url'] for s in ('worker.js','/vendor/','/models/'))]),flush=True)
    summary=browser.js("(()=>{try{const s=JSON.parse(document.getElementById('review').value);return {segments:s.length,timestamps:s.map(x=>[x.start,x.end])}}catch{return {segments:0}}})()")
    print('TRANSCRIPTION',json.dumps(summary),flush=True)
    assert status.startswith('Local transcription complete:') and summary['segments']>0, 'Synthetic default-engine transcription failed'
    assert all(0<=start<end<=31.765 for start,end in summary['timestamps']), 'Invalid synthetic timestamps'
    print('ASSESSMENT_POSTS',sum(r['method']=='POST' for r in browser.requests),flush=True)
    for relative in ['app.js','transcribe-worker.js','vendor/ort-wasm-simd-threaded.jsep.mjs','vendor/ort-wasm-simd-threaded.jsep.wasm']:
        with urllib.request.urlopen('http://127.0.0.1:8000/'+relative,timeout=15) as response:
            body=response.read();headers=response.headers
        disk=Path('static')/relative if not relative.startswith('vendor/') else Path('E:/HumanitiAI/browser-assets')/relative
        print('HTTP_AUDIT',json.dumps({'path':relative,'status':200,'mime':headers.get('Content-Type'),'cache':headers.get('Cache-Control'),
              'matches_disk':hashlib.sha256(body).digest()==hashlib.sha256(disk.read_bytes()).digest(),
              'csp':headers.get('Content-Security-Policy')}),flush=True)
    independent=browser.js("""(async()=>{
      window.Worker=class {constructor(){throw new Error('VTT import must not construct a worker');}};
      const dt=new DataTransfer();dt.items.add(new File(['WEBVTT\\n\\n00:00:01.000 --> 00:00:04.000\\nFirst synthetic caption.\\n\\n00:00:04.000 --> 00:00:08.000\\nSecond synthetic caption.\\n'],'independent.vtt',{type:'text/vtt'}));
      const input=document.getElementById('vtt');input.files=dt.files;input.dispatchEvent(new Event('change'));
      await new Promise(resolve=>setTimeout(resolve,200));const s=JSON.parse(document.getElementById('review').value);
      return {segments:s.length,timestamps:s.map(x=>[x.start,x.end]),workerNotRequired:s.length===2};
    })()""",True)
    print('INDEPENDENT_VTT',json.dumps(independent),flush=True)
    assert independent['workerNotRequired'] and independent['timestamps']==[[1,4],[4,8]]
    if args.server_loss_pid:
        import os,signal
        os.kill(args.server_loss_pid,signal.SIGTERM)
        time.sleep(.2)
        browser.js("document.getElementById('transcribe').click()")
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            message=browser.js("document.getElementById('localStatus').textContent")
            if message.startswith('Transcription failed at worker_script_load:'):break
            time.sleep(.1)
        print('SERVER_LOSS_MESSAGE',message,flush=True)
        print('SERVER_LOSS_NETWORK',json.dumps(browser.failures[-4:]),flush=True)
        assert 'Local server is unreachable' in message
        assert browser.js("JSON.parse(document.getElementById('review').value).length") == 2, 'Outage erased independent VTT review'
    assert not any(r['method']=='POST' for r in browser.requests), 'Unexpected API submission'
    browser.ws.close()


if __name__=='__main__':main()
