"""AI 추출 단계의 모델·요청 옵션 — 기본 모델로 부를 때 요청이 그대로인지, 다른 모델을 넘기면 그 모델로 부르는지.

실제 OpenAI 를 부르지 않는다. 가짜 클라이언트가 받은 인자만 본다.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
import unittest
from types import SimpleNamespace

from collect import extract_bonus, extract_conditions
from experiments.sql_semantic import applicant_type_llm as atl
from experiments.sql_semantic import industry_llm_sample as ils


class FakeClient:
    def __init__(self, payload):
        self.calls = []
        self.payload = payload
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, completion_tokens_details=None)
        message = SimpleNamespace(content=json.dumps(self.payload))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage, model=kwargs['model'])


class RequestOptionTests(unittest.TestCase):
    def test_gpt6_is_reasoning_model(self):
        self.assertTrue(ils.is_reasoning('gpt-6-luna'))
        self.assertEqual(ils.request_options('gpt-6-luna', 'medium'), {'reasoning_effort': 'medium'})

    def test_plain_model_keeps_temperature_zero(self):
        self.assertEqual(ils.request_options('gpt-4o-mini'), {'temperature': 0})

    def test_prices_have_gpt6_luna(self):
        self.assertEqual(ils.PRICES['gpt-6-luna'], (0.10, 0.50))
        self.assertEqual(extract_bonus.PRICES['gpt-6-luna'], (0.10, 0.50))


class ConditionsAskTests(unittest.TestCase):
    def test_default_request_unchanged(self):
        client = FakeClient({})
        extract_conditions.ask(client, '제목', '본문')
        call = client.calls[0]
        self.assertEqual(call['model'], 'gpt-4o-mini')
        self.assertEqual(call['temperature'], 0)
        self.assertNotIn('reasoning_effort', call)

    def test_gpt6_sends_effort_not_temperature(self):
        client = FakeClient({})
        extract_conditions.ask(client, '제목', '본문', model='gpt-6-luna', effort='medium')
        call = client.calls[0]
        self.assertEqual(call['model'], 'gpt-6-luna')
        self.assertEqual(call['reasoning_effort'], 'medium')
        self.assertNotIn('temperature', call)


class BonusAskTests(unittest.TestCase):
    def test_default_model(self):
        client = FakeClient({'status': 'none', 'items': []})
        extract_bonus.ask(client, '제목', '본문')
        self.assertEqual(client.calls[0]['model'], extract_bonus.MODEL)
        self.assertEqual(client.calls[0]['reasoning_effort'], extract_bonus.EFFORT)

    def test_override_model(self):
        client = FakeClient({'status': 'none', 'items': []})
        extract_bonus.ask(client, '제목', '본문', model='gpt-6-luna', effort='medium')
        self.assertEqual(client.calls[0]['model'], 'gpt-6-luna')

    def test_extractor_version_follows_model(self):
        self.assertEqual(extract_bonus.extractor_version(), extract_bonus.EXTRACTOR_VERSION)
        self.assertEqual(extract_bonus.extractor_version('gpt-6-luna', 'medium'),
                         'extract_bonus/%s gpt-6-luna medium' % extract_bonus.PROMPT_VERSION)


class ApplicantTypeAskTests(unittest.TestCase):
    def test_override_model(self):
        client = FakeClient({})
        atl.ask(client, {'title': '제목', 'document': '본문'}, model='gpt-6-luna', effort='medium')
        call = client.calls[0]
        self.assertEqual(call['model'], 'gpt-6-luna')
        self.assertEqual(call['reasoning_effort'], 'medium')
        self.assertNotIn('temperature', call)


if __name__ == '__main__':
    unittest.main()
