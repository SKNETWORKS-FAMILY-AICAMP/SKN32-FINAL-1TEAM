import json
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from contextlib import ExitStack
from agent_strategy.runtime import llm_runtime as runtime
from agent_strategy.functions import gpt_functions as gpt, python_functions as py
from agent_strategy.runtime import pipeline
from agent_strategy.app.testing import test_server as server
from agent_strategy.runtime.research_context import retrieve
from agent_validation_1 import validation_1 as validation


def fake_response(fid,payload):
    spec=payload.get('section_spec',{})
    text='검토 계획임'
    if spec.get('rules',{}).get('exactItems'):text='\n'.join(f'- 항목 {i} 계획임' for i in range(spec['rules']['exactItems']))
    if spec.get('rules',{}).get('stages'):text='1차 검토 후 2차 검증 계획임'
    feature_list=payload.get('source_data',{}).get('strategy_limits',{}).get('featureList',[])
    if feature_list:text += ' ' + ' '.join(str(feature) for feature in feature_list)
    tables=[]
    required=spec.get('rules',{}).get('requiredColumns',[])
    if required:
        tables=[{'columns':required,'rows':[dict((column, '테스트') for column in required)]}]
    nodes=['입력','개발','검증'] if spec.get('contentType')=='image' or fid=='F18' else []
    return {'generatedText':text,'tables':tables,'issues':[],'sourceRefs':[],'facts':[],
            'nodes':nodes,'coreFeatures':['기능'],'core_technologies':['기술'],'kpi':[{'name':str(i),'unit':'건','target':1,'measurementEnvironment':'시험'} for i in range(5)],
            'passed':True,'warnings':[],'status':'generated','model':runtime.model_config(fid)['apiModel'],
            'responseId':'fake-'+fid,'inputChars':100,'usage':{'input_tokens':10,'output_tokens':5,'total_tokens':15}}


class PipelineTests(unittest.TestCase):
    def test_early_budget_original_preserved_without_duplicate_phase_assignment(self):
        raw=self.sample('초기')
        originals=raw['2_지금_입력받는값']['_back_source']['tableData']['사업비_집행계획']
        for sid in ('3.5.3','3.5.4'):
            spec=next(s for s in runtime.CONTRACT['documents']['early_startup'] if s['sectionId']==sid)
            args=pipeline.table_arguments(raw,'early_startup',spec,{})
            output=py.generate_table(**args)
            self.assertEqual(output['tables'][0]['rows'],[])
            self.assertEqual(output['tables'][0]['rules']['unassignedOriginalRows'],originals)
            self.assertIn('단계 미지정 원본',output['generatedText'])

    def sample(self,name='예비'):
        filename={'일반':'example_general_part2.json','예비':'example_pre_startup.json','초기':'example_early_startup.json'}[name]
        raw=json.loads((Path(__file__).resolve().parents[1]/'res/back_input'/filename).read_text(encoding='utf-8'))
        # 이 통합 테스트는 전략·작성 흐름을 검증하므로 공고별 제한 검증은 전용 테스트에서 다룬다.
        raw['_strategy_limits']={'deadline':'2099-12','supportLimit':999999999999,'featureList':[]}
        normalized=pipeline.normalize_back_input(raw, {'일반':'general','예비':'pre_startup','초기':'early_startup'}[name])
        return normalized

    def mocked(self,side_effect=fake_response):
        stack=ExitStack()
        for module in [gpt,py,validation]:stack.enter_context(patch.object(module,'request_json',side_effect=side_effect))
        return stack

    def test_pipeline_all_types_and_local_evidence(self):
        for kind,name,prefix,count in [('general','일반','1.',10),('pre_startup','예비','2.',25),('early_startup','초기','3.',25)]:
            with self.mocked():result=server.run_test(self.sample(name),kind)
            self.assertEqual(len(result['results']),count)
            self.assertTrue(all(r['sectionId'].startswith(prefix) for r in result['results']))
            self.assertEqual(result['status'],'validation1_passed')
            if kind=='general': self.assertFalse(any(t['functionId']=='F17' for t in result['trace']))
            else:
                self.assertTrue(any(t['functionId']=='F17' for t in result['trace']))
                self.assertTrue(all(r['tables'] for r in result['results'] if r['functionId']=='F17'))
            self.assertLess(result['contextMetrics']['selectedSectionChars'],result['contextMetrics']['fullCanonicalCharsIfRepeated'])
            self.assertTrue(result['research']['availableFiles'])
            if kind=='pre_startup':
                budget=next(t for t in result['trace'] if t['functionId']=='F14')
                self.assertGreater(budget['output']['total'],0)
                self.assertIsNone(budget['output']['phase_1'])
                schedule=next(t for t in result['trace'] if t['functionId']=='F15')
                self.assertTrue(schedule['output']['rows'][0]['period'])
                self.assertIn('<svg',result['document']['images'][0]['svg'])

    def test_section_inputs_exclude_unrelated_team_and_budget(self):
        spec=runtime.CONTRACT['documents']['general'][0]
        source=pipeline.section_source(spec,{'item_spec':{'generatedText':'아이템'},'team_capability':'secret','budget':'money'},
               {'item':{},'period':{},'team':{},'resources':{},'budget':{},'schedule':[]},[])
        self.assertNotIn('team_capability',source)
        self.assertNotIn('budget',source)
        self.assertNotIn('team',source['originalFacts'])

    def test_impact_plan_lists_only_related_writing_sections(self):
        plan=pipeline.impact_plan('pre_startup','2.1.3')
        affected={row['sectionId'] for row in plan['affected']}
        self.assertIn('2.1.3',affected)
        self.assertIn('2.3.2',affected)
        self.assertIn('2.4.1',affected)
        self.assertNotIn('2.7.2',affected)
        self.assertTrue(pipeline.impact_plan('pre_startup','2.5.2')['affected'])

    def test_retry_regenerates_selected_and_related_sections_only(self):
        raw=self.sample('예비')
        with self.mocked():initial=server.run_test(raw,'pre_startup')
        first_trace_count=len(initial['trace'])
        plan=pipeline.impact_plan('pre_startup','2.1.3')
        affected={row['sectionId'] for row in plan['affected']}
        before={row['sectionId']:len(row.get('attempts',[])) for row in initial['results']}
        with self.mocked():retried=pipeline.retry_sections(raw,initial,'2.1.3','고객 문제를 더 구체화',render_image=server.flow_image)
        self.assertEqual(retried['retry']['selectedSectionId'],'2.1.3')
        self.assertEqual(retried['retry']['instruction'],'고객 문제를 더 구체화')
        retry_trace=retried['trace'][first_trace_count:]
        self.assertTrue(retry_trace)
        self.assertTrue(all(row['functionId'] in {'F16','F18','F19','F20'} for row in retry_trace))
        for row in retried['results']:
            if row['sectionId'] in affected:self.assertGreater(len(row.get('attempts',[])),before[row['sectionId']])
            else:self.assertEqual(len(row.get('attempts',[])),before[row['sectionId']])

    def test_model_routing_ignores_global_override(self):
        with patch.dict('os.environ',{'OPENAI_MODEL':'gpt-4.1'}):
            self.assertEqual(runtime.model_config('F03')['apiModel'],'gpt-5.6-sol')
            self.assertEqual(runtime.model_config('F02')['apiModel'],'gpt-5.6-terra')
            self.assertEqual(runtime.model_config('F05')['apiModel'],'gpt-5.6-luna')
            self.assertIsNone(runtime.model_config('F20')['apiModel'])

    def test_structural_failure_skips_semantic_call(self):
        with patch.object(validation,'request_json') as call:
            result=validation.validate_section({'rules':{'exactItems':3}}, {'generatedText':'- 하나','tables':[]}, {})
            self.assertEqual(result['status'],'fail');call.assert_not_called()

    def test_origin_and_source_checks(self):
        with patch.object(validation,'request_json') as call:
            result=validation.validate_section({'rules':{}}, {'generatedText':'예산 99원','facts':[{'path':'total','value':99}],'sourceRefs':['fake'],'tables':[]}, {'originalFacts':{'total':10}})
            self.assertEqual(result['status'],'fail');self.assertGreaterEqual(len(result['issues']),3);call.assert_not_called()

    def test_table_columns_checked_when_explicitly_requested(self):
        with patch.object(validation,'request_json') as call:
            result=validation.validate_section({'rules':{'requiredColumns':['기간']}},{'generatedText':'일정','tables':[{'columns':['내용']}]},{})
            self.assertEqual(result['status'],'fail');call.assert_not_called()

    def test_rewrite_is_bounded_and_failure_blocks_assembly(self):
        def fail(fid,payload):
            result=fake_response(fid,payload)
            if fid=='F19':result.update(passed=False,issues=['원본과 불일치'])
            return result
        with self.mocked(fail),patch.object(py,'assemble_document') as assemble:
            result=server.run_test(self.sample('일반'),'general');assemble.assert_not_called()
        self.assertIsNone(result['document']);self.assertEqual(result['status'],'validation1_failed')
        self.assertTrue(all(len(r['attempts'])==2 for r in result['results'] if r['enabled']))

    def test_rewrite_can_pass_second_attempt(self):
        counts={}
        def retry(fid,payload):
            result=fake_response(fid,payload)
            if fid=='F19':
                sid=payload['section_spec']['sectionId'];counts[sid]=counts.get(sid,0)+1
                if counts[sid]==1:result.update(passed=False,issues=['표현 수정 필요'])
            return result
        with self.mocked(retry):result=server.run_test(self.sample('일반'),'general')
        self.assertEqual(result['status'],'validation1_passed')
        self.assertTrue(all(len(r['attempts'])==2 for r in result['results'] if r['enabled']))

    def test_invalid_budget_never_calls_ai(self):
        raw=self.sample();raw['2_지금_입력받는값']['project_budget_items'][0]['total_amount']+=1
        with patch.object(py,'collect_web_data') as call:
            with self.assertRaises(ValueError):server.run_test(raw,'pre_startup')
            call.assert_not_called()

    def test_local_retrieval_bounded_and_no_unrelated_fallback(self):
        result=retrieve('반도체',char_budget=2500)
        self.assertTrue(result['sources']);self.assertLessEqual(result['contextChars'],2500)
        self.assertTrue(all(s['sourceRef'] and s['text'] for s in result['sources']))
        self.assertEqual(retrieve('zzqunknownzz')['sources'],[])

    def test_local_retrieval_expands_business_plan_development_terms(self):
        result=retrieve('개발계획 핵심기술',domains=('development',))
        self.assertEqual(result['status'],'retrieved')
        self.assertTrue(result['sources'])
        self.assertEqual(result['queryTerms'],['개발계획','핵심기술'])

    def test_image_labels_are_escaped(self):
        image=server.flow_image({'nodes':['<script>','개발','검증']})
        self.assertNotIn('<script>',image['svg']);self.assertIn('&lt;script&gt;',image['svg'])

    def test_sdk_request_model_and_usage(self):
        message=SimpleNamespace(content=json.dumps({'generatedText':'API 반환','tables':[],'issues':[],'sourceRefs':[]}))
        response=SimpleNamespace(id='test-response',usage=SimpleNamespace(model_dump=lambda:{'input_tokens':42}),choices=[SimpleNamespace(message=message)])
        with patch.dict('os.environ',{'OPENAI_API_KEY':'test-only'}),patch.object(runtime,'OpenAI') as client:
            client.return_value.chat.completions.create.return_value=response
            output=gpt.analyze_item({'description':'입력 항목'}, {})
            kwargs=client.return_value.chat.completions.create.call_args.kwargs
            self.assertEqual(kwargs['model'],'gpt-5.6-terra')
            self.assertEqual(output['usage']['input_tokens'],42)

    def test_api_errors_redacted_and_no_fallback(self):
        with patch.dict('os.environ',{'OPENAI_API_KEY':'test-only'}),patch.object(runtime,'OpenAI',side_effect=RuntimeError('sensitive provider detail')) as client:
            with self.assertRaisesRegex(RuntimeError,'F02') as caught:gpt.analyze_item({}, {})
            self.assertIn('sensitive provider detail',str(caught.exception));self.assertEqual(client.call_count,2)


if __name__=='__main__':unittest.main()


