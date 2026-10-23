import copy
import io
import json
import os
import unittest
from unittest.mock import patch
import urllib.error
from assessment import AppError, assess, build_gemini_request, parse_json, validate_request, validate_result
from synthetic import payload, result


class AssessmentTests(unittest.TestCase):
    def test_contract_rejects_raw_fields(self):
        for field in ['video','audio','frames','filename','original_transcript','replacement_mapping','label']:
            value = payload(); value[field] = 'forbidden'
            with self.assertRaises(AppError): validate_request(value)

    def test_obvious_identifiers_rejected(self):
        for value in ['contact test@example.test','call +1 202 555 0199','see class.mp4','https://school.test']:
            data = payload(); data['segments'][0]['text'] = value
            with self.assertRaises(AppError): validate_request(data)

    def test_review_and_bounds_required(self):
        data = payload(); data['reviewed'] = False
        with self.assertRaises(AppError): validate_request(data)
        data = payload(); data['segments'][0]['end'] = 121
        with self.assertRaises(AppError): validate_request(data)

    def test_insufficient_never_calls_provider(self):
        data = payload(); data['segments'] = data['segments'][:1]
        def never(*_, **__): self.fail('provider must not be called')
        with self.assertRaises(AppError) as error: assess(data, opener=never)
        self.assertEqual(error.exception.code, 'insufficient_input')

    def test_valid_evidence_derives_good(self):
        output = validate_result(result(), payload())
        self.assertEqual(output['overall_category'], 'Good')
        self.assertEqual(output['observed_dimension_mean'], 2)

    def test_hallucinated_quote_or_timestamp_rejected(self):
        for key,value in [('quote','Invented words.'),('end',999),('segment_ids',['S9999'])]:
            data = result(); data['evidence'][0][key] = value
            with self.assertRaises(AppError): validate_result(data,payload())

    def test_unobserved_is_not_zero(self):
        data = result(); data['dimensions'][0].update(status='unobserved',score=None,evidence_ids=[])
        output = validate_result(data,payload())
        self.assertEqual(output['overall_category'],'Good')
        self.assertEqual(output['observed_dimension_mean'],2)

    def test_missing_evidence_does_not_invent_rating(self):
        data = result()
        for d in data['dimensions'][:2]: d.update(status='unobserved',score=None,evidence_ids=[])
        self.assertIsNone(validate_result(data,payload())['overall_category'])

    def test_actual_visual_or_vocal_claims_rejected(self):
        for text in ['The instructor used visual modeling.', 'Lighting was excellent.', 'The vocal energy was high.']:
            data=result();data['summary']=text
            with self.assertRaises(AppError) as error:validate_result(data,payload())
            self.assertIn('unsupported_modality_claim',error.exception.message)

    def test_spoken_references_and_unassessed_aspects_allowed(self):
        data=result();data['summary']='The transcript references a visual model through spoken rectangle examples. Camera status and lighting are unassessed.'
        self.assertEqual(validate_result(data,payload())['overall_category'],'Good')

    def test_request_contains_only_approved_fields(self):
        data = build_gemini_request(payload())
        self.assertNotIn('inlineData',json.dumps(data))
        self.assertNotIn('fileData',json.dumps(data))
        self.assertEqual(set(json.loads(data['contents'][0]['parts'][0]['text'].split('\n',1)[1])), {'segments','coverage','speakers_reliable'})

    def test_duplicate_keys_and_nan_rejected(self):
        for raw in ['{"reviewed":true,"reviewed":false}','{"number":NaN}']:
            with self.assertRaises(ValueError): parse_json(raw)

    @patch.dict(os.environ,{'GEMINI_API_KEY':'synthetic-key-not-real'},clear=False)
    def test_provider_structured_plumbing(self):
        content = json.dumps({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(result())}]}}]}).encode()
        captured = []
        def fake(request,timeout): captured.append(request); return io.BytesIO(content)
        output = assess(payload(),opener=fake)
        self.assertEqual(output['overall_category'],'Good')
        self.assertNotIn('synthetic-key-not-real',captured[0].full_url)
        self.assertEqual(json.loads(captured[0].data)['generationConfig']['responseMimeType'],'application/json')

    @patch.dict(os.environ,{'GEMINI_API_KEY':'synthetic-key-not-real'},clear=False)
    def test_quota_error_sanitized(self):
        def fake(*_,**__): raise urllib.error.HTTPError('https://example.test',429,'private echo',{},io.BytesIO(b'private'))
        with self.assertRaises(AppError) as error: assess(payload(),opener=fake)
        self.assertEqual(error.exception.code,'quota_exhausted')
        self.assertNotIn('private',error.exception.message)

    @patch.dict(os.environ,{'GEMINI_API_KEY':'synthetic-key-not-real'},clear=False)
    def test_invalid_response_not_a_report(self):
        def fake(*_,**__): return io.BytesIO(b'{"candidates":[]}')
        with self.assertRaises(AppError): assess(payload(),opener=fake)


if __name__ == '__main__': unittest.main()
