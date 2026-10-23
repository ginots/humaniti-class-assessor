import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
import server
from assessment import validate_result
from synthetic import payload, result


class HTTPPrivacyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.thread = threading.Thread(target=cls.service.serve_forever,daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:'+str(cls.service.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.service.shutdown();cls.service.server_close();cls.thread.join()

    def request(self,path,body=None,headers=None):
        req=Request(self.base+path,data=body,headers=headers or {})
        try:
            with urlopen(req,timeout=5) as response: return response.status,response.headers,response.read()
        except HTTPError as error:
            data=error.read();status=error.code;headers=error.headers;error.close()
            return status,headers,data

    def test_secrets_and_private_paths_not_served(self):
        for path in ['/.env','/assessment.py','/data/recording.mp4','/vendor/../.env','/upload']:
            self.assertEqual(self.request(path)[0],404)

    def test_media_upload_rejected(self):
        status,_,_=self.request('/api/assess',b'synthetic media',{'Content-Type':'video/mp4'})
        self.assertEqual(status,415)

    def test_extra_fields_rejected_before_provider(self):
        data=payload();data['original_filename']='synthetic.mp4'
        with patch('server.assess') as call:
            status,_,_=self.request('/api/assess',json.dumps(data).encode(),{'Content-Type':'application/json'})
        self.assertEqual(status,400);call.assert_not_called()

    def test_cross_origin_rejected(self):
        status,_,_=self.request('/api/assess',b'{}',{'Content-Type':'application/json','Origin':'https://untrusted.test'})
        self.assertEqual(status,403)

    def test_unreviewed_text_rejected(self):
        data=payload();data['reviewed']=False
        status,_,_=self.request('/api/assess',json.dumps(data).encode(),{'Content-Type':'application/json'})
        self.assertEqual(status,400)

    def test_synthetic_http_assessment(self):
        server.LAST_REQUEST=0
        expected=validate_result(result(),payload())
        with patch('server.assess',return_value=expected) as call:
            status,_,raw=self.request('/api/assess',json.dumps(payload()).encode(),{'Content-Type':'application/json'})
        self.assertEqual(status,200);self.assertEqual(json.loads(raw)['overall_category'],'Good')
        self.assertEqual(set(call.call_args.args[0]),{'reviewed','deidentified','segments','coverage','speakers_reliable'})

    def test_browser_isolation_headers(self):
        status,headers,_=self.request('/')
        self.assertEqual(status,200)
        self.assertEqual(headers['Cross-Origin-Embedder-Policy'],'require-corp')
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertIn("form-action 'none'",headers['Content-Security-Policy'])


if __name__=='__main__':unittest.main()
