"""Automated isolated Chrome test; synthetic fixtures only, no body logging.

Requires websocket-client==1.9.0 in the test-only E: environment and Chrome
headless with remote debugging on localhost:9222. The application has no deps.
"""
import json
import time
import urllib.request
import websocket
import argparse
import base64
from pathlib import Path


class Browser:
    def __init__(self):
        request = urllib.request.Request('http://127.0.0.1:9222/json/new?http://127.0.0.1:8000', method='PUT')
        with urllib.request.urlopen(request, timeout=10) as response:
            tab = json.load(response)
        self.ws = websocket.create_connection(tab['webSocketDebuggerUrl'], suppress_origin=True, timeout=30)
        self.number = 0
        self.requests = []
        self.exceptions = []
        self.call('Network.enable')
        self.call('Runtime.enable')
        self.call('Page.enable')
        self.call('Target.setAutoAttach',{'autoAttach':True,'waitForDebuggerOnStart':True,'flatten':True})

    def event(self, event):
        if event.get('method') == 'Target.attachedToTarget':
            session = event['params']['sessionId']
            for method in ('Network.enable','Runtime.enable','Runtime.runIfWaitingForDebugger'):
                self.number += 1
                self.ws.send(json.dumps({'id':self.number,'method':method,'params':{},'sessionId':session}))
        elif event.get('method') == 'Network.requestWillBeSent':
            request = event['params']['request']
            # Synthetic-only test. Retain only contract metadata, never bodies.
            item = {'method':request['method'],'url':request['url'].split('?')[0],
                    'body_bytes':len(request.get('postData','').encode()),'worker':bool(event.get('sessionId'))}
            if request['method'] == 'POST':
                try:
                    body = json.loads(request.get('postData','{}'))
                    item['fields'] = sorted(body)
                    item['has_forbidden_fields'] = any(k in body for k in ('video','audio','filename','original_transcript','replacement_mapping','label'))
                    item['has_test_identifiers'] = any(term in request.get('postData','') for term in ('alice@example.test','Alice Example','Blue School','synthetic.mp4'))
                except ValueError:
                    item['non_json'] = True
            self.requests.append(item)
        elif event.get('method') == 'Runtime.exceptionThrown':
            self.exceptions.append(event['params']['exceptionDetails'].get('text','exception'))

    def call(self, method, params=None):
        self.number += 1
        number = self.number
        self.ws.send(json.dumps({'id':number,'method':method,'params':params or {}}))
        while True:
            value = json.loads(self.ws.recv())
            if value.get('id') == number:
                if 'error' in value:
                    raise RuntimeError('Browser protocol error: '+value['error']['message'])
                return value.get('result',{})
            self.event(value)

    def js(self, expression, await_promise=False):
        result = self.call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':await_promise})
        if 'exceptionDetails' in result:
            raise RuntimeError('Browser evaluation failed: '+result['exceptionDetails'].get('text','exception'))
        return result.get('result',{}).get('value')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--text-only',action='store_true')
    parser.add_argument('--vtt-assessment',action='store_true')
    args=parser.parse_args()
    browser = Browser()
    browser.call('Emulation.setDeviceMetricsOverride',{'width':1280,'height':900,'deviceScaleFactor':1,'mobile':False})
    deadline = time.monotonic()+20
    while time.monotonic()<deadline:
        if browser.js("Boolean(document.getElementById('videoTest')) && document.getElementById('health').textContent !== 'Checking assessment service…'"):
            break
        time.sleep(.2)
    print('Browser capabilities:',json.dumps(browser.js("({secure:isSecureContext,workers:!!window.Worker,wasm:!!window.WebAssembly,webcodecs:!!window.AudioDecoder,webgpu:!!navigator.gpu,crossOriginIsolated})")),flush=True)
    print('Browser version:',browser.call('Browser.getVersion').get('product'),flush=True)
    checked = browser.js("""(async()=>{
      const p=await import('/privacy.js');
      const v=p.parseVtt('WEBVTT\\n\\n1\\n00:00:01.000 --> 00:00:04.500\\n<v Alice Example>Hello, Bob.</v>\\n');
      const raw=[{start:0,end:5,text:'My name is Alice Example. Email alice@example.test or call +1 202 555 0199. Hello Bob. Blue School is here.',speaker:null}];
      const r=p.redactSegments(raw,'Alice Example\\nBob\\nBlue School');
      p.validateReviewed(r.segments,'Alice Example\\nBob\\nBlue School');
      const body=p.makePayload(r.segments,{kind:'partial',duration_seconds:5},false);
      const serial=JSON.stringify(body);
      return {vttTiming:v.segments[0].start===1&&v.segments[0].end===4.5,
        genericSpeaker:v.segments[0].speaker==='SPEAKER_1',
        identifiersRemoved:!['Alice','Bob','alice@','202 555','Blue School'].some(x=>serial.includes(x)),
        exactContract:Object.keys(body).sort().join(',')==='coverage,deidentified,reviewed,segments,speakers_reliable',
        noMapping:!('replacements' in r),changes:r.changes};
    })()""", True)
    print('Browser redaction/contract checks:',json.dumps(checked),flush=True)
    if not all(v for k,v in checked.items() if k!='changes'):
        raise SystemExit('Browser privacy check failed.')
    imported = browser.js("""(async()=>{
      const dt=new DataTransfer();dt.items.add(new File(['WEBVTT\\n\\n00:00:01.000 --> 00:00:05.000\\n<v Alice Example>My name is Alice Example. Email alice@example.test.</v>\\n'],'private-test-name.vtt',{type:'text/vtt'}));
      const input=document.getElementById('vtt');input.files=dt.files;input.dispatchEvent(new Event('change'));
      await new Promise(resolve=>setTimeout(resolve,200));
      const text=document.getElementById('review').value;
      return {localImport:text.includes('S0001'),identifiersRemoved:!text.includes('Alice')&&!text.includes('alice@'),noFilenameInReview:!text.includes('private-test-name')};
    })()""",True)
    print('VTT interface checks:',json.dumps(imported),flush=True)
    if not all(imported.values()):raise SystemExit('VTT UI import failed.')
    browser.js("document.getElementById('synthetic').click()")
    if args.vtt_assessment:
        prepared=browser.js("""(async()=>{
          const segments=JSON.parse(document.getElementById('review').value);
          const time=x=>new Date(x*1000).toISOString().slice(11,23);
          const text='WEBVTT\\n\\n'+segments.map((s,i)=>`${i+1}\\n${time(s.start)} --> ${time(s.end)}\\n${s.text}\\n`).join('\\n');
          const dt=new DataTransfer();dt.items.add(new File([text],'synthetic-class.vtt',{type:'text/vtt'}));
          const input=document.getElementById('vtt');input.files=dt.files;input.dispatchEvent(new Event('change'));
          await new Promise(resolve=>setTimeout(resolve,200));
          return {importedSegments:JSON.parse(document.getElementById('review').value).length,recordingDurationUnknown:document.getElementById('duration').value===''};
        })()""",True)
        print('VTT assessment input:',json.dumps(prepared),flush=True)
    browser.js("document.getElementById('confirm').checked=true;document.getElementById('confirm').dispatchEvent(new Event('change'));document.getElementById('assess').click();")
    end = time.monotonic()+200
    while time.monotonic()<end:
        text = browser.js("document.getElementById('assessmentStatus').textContent")
        if not text.startswith('Sending only'):
            break
        time.sleep(.5)
    print('Synthetic text assessment status:',text,flush=True)
    text_report_visible=browser.js("!document.getElementById('reportPanel').hidden")
    print('Synthetic text report visible:',text_report_visible,flush=True)
    if not text_report_visible:
        raise SystemExit('Synthetic text assessment failed; no report was invented.')
    browser.js("(async()=>{document.getElementById('reportPanel').scrollIntoView({behavior:'instant',block:'start'});await new Promise(requestAnimationFrame);return true})()",True)
    screenshot=browser.call('Page.captureScreenshot',{'format':'png'})
    destination=Path('E:/HumanitiAI/browser-assets/test')
    destination.mkdir(parents=True,exist_ok=True)
    (destination/'synthetic-report.png').write_bytes(base64.b64decode(screenshot['data']))
    browser.js('(async()=>{window.scrollTo({top:0,behavior:"instant"});await new Promise(requestAnimationFrame);return true})()',True)
    screenshot=browser.call('Page.captureScreenshot',{'format':'png'})
    (destination/'app-overview.png').write_bytes(base64.b64decode(screenshot['data']))
    if args.text_only:
        browser.js("const dt=new DataTransfer();dt.items.add(new File(['synthetic'], 'never-upload-this.mp4',{type:'video/mp4'}));const f=document.getElementById('video');f.files=dt.files;f.dispatchEvent(new Event('change'));")
        print('Changing recording clears stale review/report:',browser.js("document.getElementById('reportPanel').hidden&&document.getElementById('review').value===''&&!document.getElementById('confirm').checked&&document.getElementById('assess').disabled"),flush=True)
        posts=[r for r in browser.requests if r['method']=='POST']
        external=[r for r in browser.requests if not r['url'].startswith(('http://127.0.0.1:8000/','blob:','data:'))]
        print('Browser network inspection:',json.dumps({'post_requests':posts,'external_request_count':len(external),'uncaught_exception_count':len(browser.exceptions)}),flush=True)
        browser.ws.close()
        return
    browser.js("document.getElementById('videoTest').click()")
    end = time.monotonic()+300
    last = ''
    while time.monotonic()<end:
        text = browser.js("document.getElementById('localStatus').textContent")
        if text != last:
            print('Local video test:',text,flush=True); last=text
        if text.startswith(('Local transcription complete:','Local transcription failed:','The selected recording','WebCodecs','Transcription worker','No usable speech')):
            break
        time.sleep(1)
    summary = browser.js("""(()=>{let s;try{s=JSON.parse(document.getElementById('review').value)}catch{return {segments:0}};
      const text=s.map(x=>x.text).join(' ').toLowerCase();const duration=Number(document.getElementById('duration').value);
      return {segments:s.length,duration,containsExpectedConcepts:['fractions','number','whole'].filter(t=>text.includes(t)).length,
        timestampsValid:s.every((x,i)=>x.start>=0&&x.end>x.start&&x.end<=duration+.1&&(!i||x.start>=s[i-1].start))};})()""")
    print('Local transcription metadata:',json.dumps(summary),flush=True)
    if summary.get('segments',0)>0:
        browser.js("document.getElementById('confirm').checked=true;document.getElementById('confirm').dispatchEvent(new Event('change'));document.getElementById('assess').click()")
        end=time.monotonic()+200
        while time.monotonic()<end:
            integrated=browser.js("document.getElementById('assessmentStatus').textContent")
            if not integrated.startswith('Sending only'):break
            time.sleep(.5)
        print('Integrated recording-to-report status:',integrated,flush=True)
        print('Integrated report visible:',browser.js("!document.getElementById('reportPanel').hidden"),flush=True)
        browser.js("document.getElementById('review').value+=' ';document.getElementById('review').dispatchEvent(new Event('input'))")
        print('Editing resets consent and report:',browser.js("!document.getElementById('confirm').checked&&document.getElementById('assess').disabled&&document.getElementById('reportPanel').hidden"),flush=True)
        browser.js("document.getElementById('videoTest').click()")
        end=time.monotonic()+10
        while time.monotonic()<end:
            if browser.js("!document.getElementById('cancel').disabled"):break
            time.sleep(.1)
        browser.js("document.getElementById('cancel').click()")
        print('Cancellation clears partial transcript:',browser.js("document.getElementById('localStatus').textContent.startsWith('Cancelled.')&&document.getElementById('review').value===''"),flush=True)
    posts=[r for r in browser.requests if r['method']=='POST']
    external=[r for r in browser.requests if not r['url'].startswith(('http://127.0.0.1:8000/','blob:','data:'))]
    print('Browser network inspection:',json.dumps({'post_requests':posts,'external_request_count':len(external),'worker_requests_observed':sum(r['worker'] for r in browser.requests),'uncaught_exception_count':len(browser.exceptions)}),flush=True)
    browser.call('Page.captureScreenshot',{'format':'png'}) if False else None
    browser.ws.close()
    if summary.get('segments',0)<1 or not summary.get('timestampsValid'):
        raise SystemExit('Browser video transcription did not pass; see exact status above.')


if __name__ == '__main__':
    main()
