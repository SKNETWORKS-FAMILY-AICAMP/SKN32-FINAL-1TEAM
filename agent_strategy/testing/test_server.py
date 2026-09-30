"""Local test transport for the existing strategy functions (no replacement generation)."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone
import argparse
import json
import re
import time
import uuid
import os
import html
import threading
from openai import OpenAI
from urllib.parse import parse_qs, urlparse
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agent_strategy.runtime.llm_runtime import CONTRACT, model_config
from agent_strategy.runtime.pipeline import impact_plan, retry_sections, run_pipeline, normalize_back_input

BASE = Path(__file__).resolve().parents[1]
KINDS = {'general', 'pre_startup', 'early_startup'}
JOBS = {}
LOCK = threading.Lock()


def report_html(result):
    body = '<h1>실제 함수 실행 결과</h1><p>' + html.escape(result['message']) + '</p>'
    for row in result['results']:
        body += '<article><h2>'+html.escape(row['sectionId']+' · '+row['title'])+'</h2><pre>'+html.escape(row['generatedText'])+'</pre>'
        body += '<p>검증 1: '+html.escape(row['validation']['status'])+'</p><pre>'+html.escape(json.dumps(row['validation'],ensure_ascii=False,indent=2))+'</pre>'
        for image in row.get('images', []):
            body += image['svg']
        if row.get('tables'):
            body += '<pre>'+html.escape(json.dumps(row['tables'], ensure_ascii=False, indent=2))+'</pre>'
        body += '</article>'
    return '<!doctype html><html lang="ko"><meta charset="utf-8"><title>실행 결과</title><style>body{max-width:1100px;margin:30px auto;font:15px/1.7 sans-serif}pre{white-space:pre-wrap}article{border-top:1px solid #ddd;padding:20px}svg{width:100%;height:auto}</style>'+body+'</html>'


def flow_image(output):
    nodes = output.get('nodes')
    if not isinstance(nodes, list) or not 3 <= len(nodes) <= 6 or not all(isinstance(n, str) and 0 < len(n) <= 35 for n in nodes):
        nodes=['사용자 입력','AI 분석·처리','결과 확인']
        output['nodes']=nodes
        output['flowType']='USER_FLOW'
        output.setdefault('warnings',[]).append('모델 nodes 형식 오류로 기본 USER_FLOW 흐름도를 사용함')
    width = 1100 / len(nodes)
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1140 200"><rect width="1140" height="200" fill="#f4f6fa"/>'
    for i, node in enumerate(nodes):
        x = 20 + i * width
        svg += f'<rect x="{x}" y="65" width="{width-22}" height="65" rx="10" fill="#2457d6"/><text x="{x+(width-22)/2}" y="104" text-anchor="middle" font-family="sans-serif" font-size="14" fill="white">{html.escape(node)}</text>'
        if i < len(nodes)-1:
            svg += f'<text x="{x+width-21}" y="104" fill="#2457d6">→</text>'
    svg += '<text x="20" y="170" font-family="sans-serif" font-size="14">AI 생성 명세 기반 개념도 · 상세 설계 검토 필요</text></svg>'
    return {'mimeType':'image/svg+xml', 'svg':svg, 'origin':'generate_image_spec.nodes', 'status':'proposed'}


def run_test(raw, kind, progress=None, execution_scope='full'):
    return run_pipeline(raw, kind, progress, render_image=flow_image, execution_scope=execution_scope)


def save_result(result):
    # Keep an immutable history even when the same input is run repeatedly.
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
    out = BASE/'res/to_back'/'runs'/f"{stamp}_{result['documentType']}_{result['runId']}"
    out.mkdir(parents=True)
    validation_results=[{'sectionId':row.get('sectionId'),'title':row.get('title'),'status':row.get('validation',{}).get('status'),'issues':row.get('validation',{}).get('issues',[]),'warnings':row.get('validation',{}).get('warnings',[]),'agent':row.get('validation',{}).get('agent','검증 1'),'attempts':row.get('attempts',[])} for row in result.get('results',[]) if row.get('validation')]
    result['validation_results']=validation_results
    (out/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (out/'validation.json').write_text(json.dumps({'runId':result['runId'],'documentType':result['documentType'],'status':result['status'],'validation1':validation_results}, ensure_ascii=False, indent=2), encoding='utf-8')
    (out/'result.html').write_text(report_html(result), encoding='utf-8')
    (out/'manifest.json').write_text(json.dumps({
        'runId': result['runId'], 'createdAt': result['createdAt'],
        'documentType': result['documentType'], 'status': result['status'],
        'retry': result.get('retry'), 'files': ['result.json', 'validation.json', 'result.html']
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(out)


def public_job(job):
    return {key:value for key,value in job.items() if not key.startswith('_')}


def run_job(job_id, body):
    try:
        def progress(message, count):
            JOBS[job_id].update(message=message, completedCalls=count)
        raw=body['input']; contract=raw.get('2_지금_입력받는값') if isinstance(raw,dict) else None
        valid=(isinstance(raw,dict) and ((isinstance(raw.get('tableData'),dict) and raw['tableData']) or (isinstance(contract,dict) and contract.get('POST_projects_body',{}).get('description'))))
        if not valid:
            files={'general':'example_general_part2.json','pre_startup':'example_pre_startup.json','early_startup':'example_early_startup.json'}
            raw=json.loads((BASE/'res/from_back'/files[body['documentType']]).read_text(encoding='utf-8'))
            body=dict(body,input=raw)
            JOBS[job_id].update(message='입력 JSON이 비어 있어 현재 유형 back JSON으로 자동 보정')
        result = run_test(raw, body['documentType'], progress, body.get('executionScope','full'))
        JOBS[job_id].update(status='done', result=result, outputDirectory=save_result(result))
    except Exception as exc:
        partial={'documentType':body.get('documentType'),'status':'error_partial','message':'오류 발생 전까지 생성된 결과를 저장했습니다.','error':str(exc),'trace':getattr(exc,'partial_trace',[]),'results':[],'document':None}
        JOBS[job_id].update(status='error', error=str(exc), result=partial, outputDirectory=save_result(partial), partialResult=partial)
    finally:
        LOCK.release()


def run_retry_job(job_id, parent_job, section_id, instruction):
    try:
        def progress(message, count):
            JOBS[job_id].update(message=message, completedCalls=count)
        result=retry_sections(parent_job['_input'],parent_job['result'],section_id,instruction,progress,render_image=flow_image)
        JOBS[job_id].update(status='done',result=result,outputDirectory=save_result(result))
    except Exception as exc:
        JOBS[job_id].update(status='error',error=str(exc))
    finally:
        LOCK.release()

def run_validate_job(job_id, parent_job, section_id):
    try:
        kind=parent_job['result']['documentType']; plan=impact_plan(kind,section_id)
        specs={s['sectionId']:s for s in CONTRACT['documents'][kind]}
        rows={r['sectionId']:r for r in parent_job['result'].get('results',[])}
        checked=[]
        for item in plan['affected']:
            spec=specs[item['sectionId']]; row=rows.get(item['sectionId'])
            if not row: continue
            result=py.validate_section(section_spec=spec,content={'generatedText':row.get('generatedText',''),'tables':row.get('tables',[])},source_data={})
            row['validation']=result; checked.append(item['sectionId'])
        parent_job['result']['validation1']=[{'sectionId':sid,'status':rows[sid]['validation'].get('status'),'issues':rows[sid]['validation'].get('issues',[])} for sid in checked]
        parent_job['result']['status']='validation1_failed' if any(rows[sid]['validation'].get('status')=='fail' for sid in checked) else 'validation1_passed'
        parent_job['result']['message']='선택 항목 및 연관 항목 검증 1 완료.'
        JOBS[job_id].update(status='done',result=parent_job['result'],outputDirectory=save_result(parent_job['result']),message='선택 항목 및 연관 항목 검증 1 완료',completedCalls=len(checked))
    except Exception as exc:
        JOBS[job_id].update(status='error',error=str(exc))
    finally: LOCK.release()

def run_validate_all_job(job_id, result):
    try:
        specs={s['sectionId']:s for s in CONTRACT['documents'][result['documentType']]}
        for row in result.get('results',[]):
            spec=specs.get(row['sectionId'])
            if spec and spec.get('enabled'):
                row['validation']=py.validate_section(spec,{'generatedText':row.get('generatedText',''),'tables':row.get('tables',[])},{})
        failed=any(r.get('validation',{}).get('status')=='fail' for r in result['results'])
        result['status']='validation1_failed' if failed else 'validation1_passed'
        if not failed: result['document']=py.assemble_document(result['results'],[t for r in result['results'] for t in r.get('tables',[])],[i for r in result['results'] for i in r.get('images',[])])
        result['message']='전체 항목 검증 1 및 조립 완료.' if not failed else '검증 1 미통과 항목이 있어 조립을 보류했습니다.'
        JOBS[job_id].update(status='done',result=result,outputDirectory=save_result(result),message=result['message'])
    except Exception as exc: JOBS[job_id].update(status='error',error=str(exc))
    finally: LOCK.release()


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, payload, content_type='application/json; charset=utf-8'):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        # The canonical UI is intentionally usable through file:// as well as
        # through this local server.  Limit CORS to that opaque file origin and
        # this server's two loopback origins; never expose a wildcard origin.
        origin = self.headers.get('Origin')
        allowed = {None, 'null', f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
        if origin in allowed and origin is not None:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        origin = self.headers.get('Origin')
        allowed = {'null', f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
        if origin not in allowed:
            return self.respond(403, {'error': 'Local UI only.'})
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', origin)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Vary', 'Origin')
        self.end_headers()

    def do_GET(self):
        parsed=urlparse(self.path)
        if parsed.path.startswith('/api/jobs/'):
            job=JOBS.get(parsed.path.rsplit('/',1)[-1])
            return self.respond(200, public_job(job) if job else {'status':'error','error':'Unknown run'})
        if parsed.path == '/api/impact':
            query=parse_qs(parsed.query)
            try:
                return self.respond(200,impact_plan(query.get('documentType',[''])[0],query.get('sectionId',[''])[0]))
            except ValueError as exc:
                return self.respond(400,{'error':str(exc)})
        if self.path == '/api/status':
            configured=bool(os.getenv('OPENAI_API_KEY')); reachable=False; detail='키가 설정되지 않았습니다.' if not configured else ''
            if configured:
                try: OpenAI(timeout=8,max_retries=0).models.list(); reachable=True; detail='OpenAI API 연결 성공'
                except Exception as exc:
                    raw=' '.join(str(exc).split())
                    detail='OpenAI 크레딧·사용 한도 초과(insufficient_quota)' if 'insufficient_quota' in raw or 'no credits' in raw else f'{type(exc).__name__}: 연결 실패'
            return self.respond(200, {'apiKeyConfigured':configured,'apiReachable':reachable,'apiStatus':detail,'model':'함수별 GPT-5.6 Sol / Terra / Luna','models':{fid:model_config(fid) for fid in CONTRACT['functions']},'validationAgent':'검증 1','tableGenerationEnabled':False})
        if self.path in ['/', '/test']:
            return self.respond(200, (BASE/'strategy_writing_agent.html').read_bytes(), 'text/html; charset=utf-8')
        if self.path == '/api/examples':
            files = {'general':'example_general_part2.json','pre_startup':'example_pre_startup.json','early_startup':'example_early_startup.json'}
            examples = {k: json.loads((BASE/'res/from_back'/name).read_text(encoding='utf-8')) for k,name in files.items()}
            return self.respond(200, examples)
        if parsed.path == '/api/latest-results':
            runs=BASE/'res/to_back'/'runs'; latest={}
            if runs.exists():
                for kind in KINDS:
                    matches=sorted(runs.glob(f'*_{kind}_*/result.json'),key=lambda p:p.stat().st_mtime,reverse=True)
                    if matches:
                        try: latest[kind]=json.loads(matches[0].read_text(encoding='utf-8'))
                        except Exception: pass
            return self.respond(200,latest)
        if self.path == '/api/section-mapping':
            mapping=json.loads((BASE/'res/from_back'/'section_mapping.json').read_text(encoding='utf-8'))
            mapping['executionSourceKeys']={kind:{spec['sectionId']:spec['sourceKeys'] for spec in specs} for kind,specs in CONTRACT['documents'].items()}
            mapping['rewriteDependencies']={}
            for kind,specs in CONTRACT['documents'].items():
                mapping['rewriteDependencies'][kind]={}
                for spec in specs:
                    try: mapping['rewriteDependencies'][kind][spec['sectionId']]=impact_plan(kind,spec['sectionId'])['rewriteFunctions']
                    except ValueError: mapping['rewriteDependencies'][kind][spec['sectionId']]={'selected':spec['functionId'],'upstreamStrategy':[],'downstreamWriting':[],'validation':['F19'],'assembly':['F20'],'executionNote':'표 생성 제외'}
            return self.respond(200, mapping)
        self.respond(404, {'error':'not found'})

    def do_POST(self):
        # Serve the UI and API on one loopback origin; no wildcard CORS or file origin writes.
        if self.headers.get('Origin') not in {None, 'null', f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}:
            return self.respond(403, {'error':'Open the local test page.'})
        if self.path not in ['/api/run','/api/retry','/api/retry-latest','/api/validate-latest','/api/validate-all-latest']:
            return self.respond(404, {'error':'not found'})
        acquired=False
        try:
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size <= 2_000_000:
                raise ValueError('입력 크기는 2MB 이하여야 합니다.')
            body = json.loads(self.rfile.read(size))
            if not os.getenv('OPENAI_API_KEY'):
                raise ValueError('서버에 OPENAI_API_KEY가 없습니다. start_function_test.cmd에서 입력하세요.')
            if not LOCK.acquire(blocking=False):
                return self.respond(409, {'error':'현재 실행이 진행 중입니다.'})
            acquired=True
            job_id = str(uuid.uuid4())
            if self.path == '/api/run':
                if body.get('documentType') not in KINDS or not isinstance(body.get('input'), dict) or body.get('executionScope','full') not in {'full','strategy_writing'}:
                    raise ValueError('문서 유형과 입력 JSON을 확인하세요.')
                JOBS[job_id] = {'status':'running','message':'함수 실행 준비 중','completedCalls':0,'_input':body['input'],'executionScope':body.get('executionScope','full')}
                threading.Thread(target=run_job, args=(job_id,body), daemon=True).start()
            elif self.path == '/api/validate-all-latest':
                kind=body.get('documentType'); runs=BASE/'res/to_back'/'runs'; files=sorted(runs.glob(f'*_{kind}_*/result.json'),key=lambda p:p.stat().st_mtime,reverse=True)
                if not files or kind not in KINDS: raise ValueError('최신 실행 결과와 사업계획서 유형이 필요합니다.')
                saved=json.loads(files[0].read_text(encoding='utf-8')); JOBS[job_id]={'status':'running','message':'전체 검증 및 조립 준비 중','completedCalls':0}
                threading.Thread(target=run_validate_all_job,args=(job_id,saved),daemon=True).start()
            elif self.path == '/api/validate-latest':
                kind=body.get('documentType'); section_id=body.get('sectionId'); runs=BASE/'res/to_back'/'runs'; files=sorted(runs.glob(f'*_{kind}_*/result.json'),key=lambda p:p.stat().st_mtime,reverse=True)
                if not files or kind not in KINDS or not isinstance(section_id,str): raise ValueError('최신 실행 결과와 사업계획서 항목 위치가 필요합니다.')
                saved=json.loads(files[0].read_text(encoding='utf-8')); parent={'result':saved}; plan=impact_plan(kind,section_id)
                JOBS[job_id]={'status':'running','message':'선택 항목 및 연관 항목 검증 준비 중','completedCalls':0,'impact':plan}
                threading.Thread(target=run_validate_job,args=(job_id,parent,section_id),daemon=True).start()
            elif self.path == '/api/retry-latest':
                kind=body.get('documentType'); section_id=body.get('sectionId'); runs=BASE/'res/to_back'/'runs'; files=sorted(runs.glob(f'*_{kind}_*/result.json'),key=lambda p:p.stat().st_mtime,reverse=True)
                if not files or kind not in KINDS or not isinstance(section_id,str): raise ValueError('최신 실행 결과와 사업계획서 항목 위치가 필요합니다.')
                saved=json.loads(files[0].read_text(encoding='utf-8')); back=json.loads((BASE/'res/from_back'/{'general':'example_general_part2.json','pre_startup':'example_pre_startup.json','early_startup':'example_early_startup.json'}[kind]).read_text(encoding='utf-8')); parent={'result':saved,'_input':normalize_back_input(back,kind)}
                plan=impact_plan(kind,section_id); JOBS[job_id]={'status':'running','message':'최신 저장 결과 기준 재작성 준비 중','completedCalls':0,'_input':parent['_input'],'_parentJobId':'latest','impact':plan}
                threading.Thread(target=run_retry_job,args=(job_id,parent,section_id,body.get('instruction','')),daemon=True).start()
            else:
                parent=JOBS.get(body.get('parentJobId'))
                section_id=body.get('sectionId')
                instruction=body.get('instruction','')
                if not parent or parent.get('status')!='done' or not isinstance(section_id,str):
                    raise ValueError('완료된 실행 결과와 사업계획서 항목 위치가 필요합니다.')
                if not isinstance(instruction,str) or len(instruction)>1200:
                    raise ValueError('재시도 지시는 1,200자 이하여야 합니다.')
                plan=impact_plan(parent['result']['documentType'],section_id)
                JOBS[job_id]={'status':'running','message':'선택 항목 및 연관 항목 재시도 준비 중','completedCalls':0,'_input':parent['_input'],'_parentJobId':body['parentJobId'],'impact':plan}
                threading.Thread(target=run_retry_job,args=(job_id,parent,section_id,instruction),daemon=True).start()
            self.respond(202, {'jobId':job_id})
        except (ValueError, KeyError, TypeError) as exc:
            if acquired: LOCK.release()
            self.respond(400, {'error':str(exc)})
        except Exception as exc:
            if acquired: LOCK.release()
            self.respond(500, {'error': f'{type(exc).__name__}: {exc}'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not os.getenv('OPENAI_API_KEY'):
        from getpass import getpass
        os.environ['OPENAI_API_KEY'] = getpass('OpenAI API key (hidden, session only): ').strip()
    print(f'Function test: http://127.0.0.1:{args.port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
