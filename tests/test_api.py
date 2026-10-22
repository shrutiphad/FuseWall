import json
import tempfile
import unittest
import sqlite3
from unittest.mock import patch
from pathlib import Path
from fastapi.testclient import TestClient
from fusewall.app import create_app
from tests.support import WorkspaceDirectory

HEADERS = {"X-Fusewall-Request":"dashboard"}


class APITests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parent.parent / 'test-results' / 'tmp'
        scratch.mkdir(parents=True, exist_ok=True)
        self.tmp = WorkspaceDirectory(dir=scratch)
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.token = self.app.state.store.admin_path.read_text().strip()

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.tmp.cleanup()

    def login(self):
        result = self.client.post('/api/login',json={"token":self.token},headers=HEADERS)
        self.assertEqual(result.status_code,200,result.text)

    def key(self, **kwargs):
        self.login()
        result = self.client.post('/api/keys',json={"name":"API test",**kwargs},headers=HEADERS)
        self.assertEqual(result.status_code,200,result.text)
        return result.json()

    def completion(self, key, **kwargs):
        return self.client.post('/v1/chat/completions',headers={"Authorization":"Bearer "+key['token'],"X-Fusewall-Session":"sdk"},json={"messages":[{"role":"user","content":"Hello"}],**kwargs})

    def test_health_and_frontend(self):
        self.assertEqual(self.client.get('/health/ready').status_code,200)
        html = self.client.get('/')
        self.assertIn('Fusewall',html.text)
        self.assertEqual(html.headers['x-frame-options'],'DENY')
        self.assertEqual(self.client.get('/static/app.js').status_code,200)

    def test_owner_access_cookie_and_logout(self):
        self.assertEqual(self.client.get('/api/state').status_code,401)
        self.login()
        self.assertEqual(self.client.get('/api/state').status_code,200)
        self.client.post('/api/logout',headers=HEADERS)
        self.assertEqual(self.client.get('/api/state').status_code,401)

    def test_cross_origin_writes_and_missing_header_rejected(self):
        a = self.client.post('/api/login',json={"token":self.token},headers={**HEADERS,"Origin":"https://attacker.example"})
        self.assertEqual(a.status_code,403)
        self.assertEqual(self.client.post('/api/login',json={"token":self.token}).status_code,403)

    def test_dns_rebinding_host_rejected(self):
        self.assertEqual(self.client.get('/health/live',headers={"Host":"attacker.example"}).status_code,400)

    def test_oversized_body_rejected(self):
        self.assertEqual(self.client.post('/api/login',content=b'x'*70_000,headers=HEADERS).status_code,413)

    def test_workload_key_cannot_grant_owner_permissions(self):
        key = self.key()
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/state',headers={"Authorization":"Bearer "+key['token']}).status_code,401)
        self.assertEqual(self.completion(key).status_code,200)
        self.assertEqual(self.client.patch('/api/settings',headers={**HEADERS,'Authorization':'Bearer '+key['token']},json={'paused':False,'budget_micro':999999}).status_code,401)

    def test_owner_token_is_not_a_workload_key(self):
        r = self.client.post('/v1/chat/completions',headers={"Authorization":"Bearer "+self.token},json={"messages":[{"role":"user","content":"Hi"}]})
        self.assertEqual(r.status_code,401)

    def test_non_streaming_completion_and_receipt(self):
        response = self.completion(self.key())
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['fusewall']['mode'],'simulation')
        self.assertGreater(response.json()['usage']['completion_tokens'],0)
        self.assertTrue(self.app.state.store.integrity()['ok'])

    def test_streaming_contract_and_usage(self):
        response = self.completion(self.key(),stream=True,max_tokens=4)
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn('text/event-stream',response.headers['content-type'])
        lines = [line[6:] for line in response.text.splitlines() if line.startswith('data: ')]
        self.assertEqual(lines[-1],'[DONE]')
        self.assertEqual(json.loads(lines[-2])['usage']['completion_tokens'],4)
        self.assertEqual(self.app.state.store.overview()['held_micro'],0)

    def test_unsupported_fields_and_unknown_model_rejected(self):
        key = self.key()
        for fields in ({'model':'unknown'},{'upstream_url':'http://169.254.169.254'},{'session_budget_micro':999999},{'tools':[]}):
            self.assertEqual(self.completion(key,**fields).status_code,422)

    def test_validation_never_echoes_input(self):
        self.login()
        r = self.client.post('/api/keys',json={"name":"Test", "budget_micro":"PRIVATE CREDENTIAL"},headers=HEADERS)
        self.assertEqual(r.status_code,422)
        self.assertNotIn('PRIVATE CREDENTIAL',r.text)

    def test_float_and_negative_money_rejected(self):
        self.login()
        for amount in (-1,1.5,'12'):
            self.assertEqual(self.client.post('/api/keys',json={"name":"Bad","budget_micro":amount},headers=HEADERS).status_code,422)

    def test_model_allowlist(self):
        key = self.key()
        self.assertEqual(self.completion(key,model='fusewall/pro').status_code,403)
        self.assertEqual(len(self.client.get('/v1/models',headers={"Authorization":"Bearer "+key['token']}).json()['data']),1)

    def test_lab_concurrent_ceiling(self):
        key = self.key(session_budget_micro=7000)
        r = self.client.post('/api/lab',json={"key_id":key['id'],"session_id":"loop","calls":12,"parallel":4},headers=HEADERS)
        self.assertEqual(r.status_code,200,r.text)
        self.assertGreater(r.json()['summary']['blocked'],0)
        self.assertTrue(self.app.state.store.integrity()['ok'])
        self.assertLessEqual(self.app.state.store.overview()['spent_micro'],7000)

    def test_partial_and_known_failure_accounting(self):
        key = self.key()
        for scenario in ('provider_error','interrupted'):
            r = self.client.post('/api/lab',json={"key_id":key['id'],"session_id":scenario,"scenario":scenario},headers=HEADERS)
            self.assertEqual(r.json()['summary']['failed'],1)
        self.assertEqual(self.app.state.store.overview()['held_micro'],0)
        self.assertTrue(self.app.state.store.integrity()['ok'])

    def test_revoked_key_rejected(self):
        key = self.key()
        self.client.patch('/api/keys/'+key['id'],json={"active":False},headers=HEADERS)
        self.assertEqual(self.completion(key).status_code,401)

    def test_backup_integrity_and_csv_formula_safety(self):
        key = self.key(name='=HYPERLINK("example")')
        self.completion(key)
        self.assertIn("'=HYPERLINK",self.client.get('/api/export').text)
        self.assertTrue(self.client.post('/api/backup',headers=HEADERS).content.startswith(b'SQLite format 3'))
        self.assertTrue(self.client.post('/api/integrity',headers=HEADERS).json()['ok'])

    def test_unavailable_authority_returns_503_without_dispatch(self):
        key = self.key()
        before = self.app.state.store.overview()['requests']
        with patch.object(self.app.state.store,'connect',side_effect=sqlite3.OperationalError('test unavailable')):
            self.assertEqual(self.completion(key).status_code,503)
        self.assertEqual(self.app.state.store.overview()['requests'],before)

    def test_preview_is_owner_only_validated_and_nonmutating(self):
        key = self.key()
        payload = {'key_id':key['id'],'session_id':'preview','completion':{'messages':[{'role':'user','content':'Hi'}]}}
        before = self.app.state.store.overview()['requests']
        r = self.client.post('/api/preview',json=payload,headers=HEADERS)
        self.assertEqual(r.status_code,200,r.text)
        self.assertTrue(r.json()['allowed'])
        self.assertEqual(self.app.state.store.overview()['requests'],before)
        self.assertEqual(self.app.state.store.sessions(),[])
        self.client.cookies.clear()
        self.assertEqual(self.client.post('/api/preview',json=payload,headers={**HEADERS,'Authorization':'Bearer '+key['token']}).status_code,401)

    def test_full_history_and_receipt_contracts(self):
        key = self.key()
        completion = self.completion(key).json()
        r = self.client.get('/api/requests',params={'limit':1,'search':'API test','status':'settled'})
        self.assertEqual(r.json()['total'],1)
        receipt = self.client.get('/api/requests/'+completion['id'])
        self.assertEqual(receipt.status_code,200)
        self.assertIn('events',receipt.json())
        self.assertNotIn('fingerprint',receipt.json())
        self.assertEqual(self.client.get('/api/requests/missing').status_code,404)
        self.assertEqual(self.client.get('/api/requests?offset=999999').status_code,422)
        self.assertEqual(self.client.get('/api/requests?status=typo').status_code,400)
        self.assertEqual(self.client.get('/api/insights').json()['totals']['requests'],1)
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/insights').status_code,401)
        self.assertEqual(self.client.get('/api/requests/'+completion['id']).status_code,401)

    def test_malformed_host_is_rejected_without_server_error(self):
        self.assertEqual(self.client.get('/health/live',headers={'Host':'[broken'}).status_code,400)

    def test_boolean_and_reconciliation_contracts_are_strict(self):
        key = self.key()
        self.assertEqual(self.completion(key,stream='false').status_code,422)
        self.assertEqual(self.client.patch('/api/keys/'+key['id'],json={'active':'false'},headers=HEADERS).status_code,422)
        self.assertEqual(self.client.patch('/api/settings',json={'budget_micro':1000000,'paused':1},headers=HEADERS).status_code,422)
        self.assertEqual(self.client.post('/api/requests/missing/resolve',json={'actual_micro':0,'reason':'        '},headers=HEADERS).status_code,422)


if __name__ == '__main__': unittest.main()
