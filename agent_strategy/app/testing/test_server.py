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
import traceback
import hashlib
from openai import OpenAI
from urllib.parse import parse_qs, urlparse
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agent_strategy.runtime.llm_runtime import CONTRACT, model_config
from agent_strategy.runtime.pipeline import impact_plan, retry_sections, run_pipeline, normalize_back_input, _reconcile_validation
from agent_validation_1.scoring import score_section, aggregate_scores
from agent_strategy.functions import gpt_functions as gpt, python_functions as py
try:
    from agent_validation_1.validation_1 import VALIDATION_POLICY_VERSION
except ModuleNotFoundError:
    # strategy 브랜치만 분리해 실행할 때도 F01~F18 UI는 시작할 수 있게 한다.
    VALIDATION_POLICY_VERSION='validation-agent-unavailable'

BASE = Path(__file__).resolve().parents[2]
KINDS = {'general', 'pre_startup', 'early_startup'}
JOBS = {}
LOCK = threading.Lock()

def _content_hash(content):
    return hashlib.sha256(json.dumps(content,ensure_ascii=False,sort_keys=True,default=str).encode('utf-8')).hexdigest()


def report_html(result):
    body = '<h1>실제 함수 실행 결과</h1><p>' + html.escape(str(result.get('message','부분 실행 결과'))) + '</p>'
    for row in result['results']:
        section_id=str(row.get('sectionId','알 수 없는 항목'))
        title=str(row.get('title',''))
        generated=row.get('generatedText','')
        validation=row.get('validation') or {'status':'not_run','issues':['부분 결과로 검증되지 않음']}
        body += '<article><h2>'+html.escape(section_id+' · '+title)+'</h2><pre>'+html.escape(str(generated))+'</pre>'
        body += '<p>검증 1: '+html.escape(str(validation.get('status','not_run')))+'</p><pre>'+html.escape(json.dumps(validation,ensure_ascii=False,indent=2))+'</pre>'
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
    flow_type = output.get('flowType','USER_FLOW')
    title = 'USERFLOW' if flow_type == 'USER_FLOW' else '서비스 구조도'
    colors = ['#2563eb','#7c3aed','#0891b2','#059669','#d97706','#db2777']
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1140 230"><rect width="1140" height="230" rx="16" fill="#f8fafc"/><text x="40" y="38" font-family="sans-serif" font-size="22" font-weight="700" fill="#172033">{title}</text>'
    for i, node in enumerate(nodes):
        x = 20 + i * width
        svg += f'<rect x="{x}" y="65" width="{width-22}" height="65" rx="12" fill="{colors[i%len(colors)]}"/><text x="{x+(width-22)/2}" y="104" text-anchor="middle" font-family="sans-serif" font-size="14" font-weight="600" fill="white">{html.escape(node)}</text>'
        if i < len(nodes)-1:
            svg += f'<text x="{x+width-21}" y="104" fill="#2457d6">→</text>'
    svg += '<text x="40" y="185" font-family="sans-serif" font-size="13" fill="#667085">AI 생성 명세 기반 개념도 · 상세 설계 검토 필요</text></svg>'
    return {'mimeType':'image/svg+xml', 'svg':svg, 'origin':'generate_image_spec.nodes', 'status':'proposed'}


def run_test(raw, kind, progress=None, execution_scope='full'):
    return run_pipeline(raw, kind, progress, render_image=flow_image, execution_scope=execution_scope)


def save_result(result):
    # Keep an immutable history even when the same input is run repeatedly.
    result.setdefault('runId',str(uuid.uuid4()))
    result.setdefault('createdAt',datetime.now(timezone.utc).isoformat())
    result.setdefault('documentType','unknown')
    result.setdefault('status','error_partial')
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
    out = BASE/'res/back_output'/'runs'/f"{stamp}_{result['documentType']}_{result['runId']}"
    out.mkdir(parents=True)
    validation_results=[{'sectionId':row.get('sectionId'),'title':row.get('title'),'status':row.get('validation',{}).get('status'),'issues':row.get('validation',{}).get('issues',[]),'warnings':row.get('validation',{}).get('warnings',[]),'agent':row.get('validation',{}).get('agent','검증 1'),'attempts':row.get('attempts',[])} for row in result.get('results',[]) if row.get('validation')]
    result['validation_results']=validation_results
    (out/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (out/'validation.json').write_text(json.dumps({'runId':result['runId'],'documentType':result['documentType'],'status':result['status'],'validation1':validation_results}, ensure_ascii=False, indent=2), encoding='utf-8')
    (out/'result.html').write_text(report_html(result), encoding='utf-8')
    image_files=[]
    for row in result.get('results',[]):
        for idx,image in enumerate(row.get('images',[]) or []):
            svg=image.get('svg') if isinstance(image,dict) else None
            if svg:
                name=f"{row.get('sectionId','section')}_{idx+1}.svg"
                (out/name).write_text(svg, encoding='utf-8')
                image_files.append(name)
    (out/'manifest.json').write_text(json.dumps({
        'runId': result['runId'], 'createdAt': result['createdAt'],
        'documentType': result['documentType'], 'status': result['status'],
        'retry': result.get('retry'), 'files': ['result.json', 'validation.json', 'result.html'] + image_files
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(out)


def public_job(job):
    return {key:value for key,value in job.items() if not key.startswith('_')}

def validation_source_for(row, content):
    stored=row.get('validationSource')
    if isinstance(stored, dict) and (stored.get('originalFacts') or stored.get('evidence') or stored.get('sourceRefs')):
        return stored
    return {'originalFacts':content.get('originalFacts',{}),'evidence':content.get('evidence',[]),
            'sourceRefs':content.get('sourceRefs',[]),'_fallbackValidationSource':True}


def run_job(job_id, body):
    try:
        def progress(message, count):
            if JOBS.get(job_id, {}).get('cancelRequested'):
                raise RuntimeError('사용자가 실행을 중단했습니다.')
            JOBS[job_id].update(message=message, completedCalls=count)
            print(f'[{job_id[:8]}] {message} · 완료 호출 수: {count}', flush=True)
        raw=body['input']; contract=raw.get('2_지금_입력받는값') if isinstance(raw,dict) else None
        valid=(isinstance(raw,dict) and ((isinstance(raw.get('tableData'),dict) and raw['tableData']) or (isinstance(contract,dict) and contract.get('POST_projects_body',{}).get('description'))))
        if not valid:
            files={'general':'example_general_part2.json','pre_startup':'example_pre_startup.json','early_startup':'example_early_startup.json'}
            raw=json.loads((BASE/'res/back_input'/files[body['documentType']]).read_text(encoding='utf-8'))
            body=dict(body,input=raw)
            JOBS[job_id].update(message='입력 JSON이 비어 있어 현재 유형 back JSON으로 자동 보정')
        result = run_test(raw, body['documentType'], progress, body.get('executionScope','full'))
        JOBS[job_id].update(status='done', result=result, outputDirectory=save_result(result))
    except Exception as exc:
        partial={'runId':str(uuid.uuid4()),'createdAt':datetime.now(timezone.utc).isoformat(),
                 'documentType':body.get('documentType'),'status':'error_partial',
                 'message':'오류 발생 전까지 생성된 결과를 저장했습니다.',
                 'error':str(exc),'errorType':type(exc).__name__,
                 'errorTraceback':traceback.format_exc(),
                 'trace':getattr(exc,'partial_trace',[]),
                 'results':getattr(exc,'partial_results',[]),
                 'images':getattr(exc,'partial_images',[]), 'document':None}
        output_directory=None
        try:
            output_directory=save_result(partial)
        except Exception as save_exc:
            partial['saveError']=str(save_exc)
        cancelled=bool(JOBS.get(job_id, {}).get('cancelRequested'))
        if cancelled:
            partial['status']='cancelled_partial'
            partial['message']='사용자 요청으로 실행을 중단했습니다. 완료된 결과만 저장했습니다.'
        JOBS[job_id].update(status='error', error=str(exc), errorType=type(exc).__name__,
                            errorTraceback=traceback.format_exc(), result=partial,
                            outputDirectory=output_directory, partialResult=partial)
    finally:
        LOCK.release()


def run_retry_job(job_id, parent_job, section_id, instruction, mode='manual'):
    try:
        def progress(message, count):
            if JOBS.get(job_id, {}).get('cancelRequested'):
                raise RuntimeError('사용자가 실행을 중단했습니다.')
            JOBS[job_id].update(message=message, completedCalls=count)
        result=retry_sections(parent_job['_input'],parent_job['result'],section_id,instruction,progress,render_image=flow_image)
        if result.get('retryHistory'):
            result['retryHistory'][-1]['mode']=mode
        JOBS[job_id].update(status='done',result=result,outputDirectory=save_result(result))
    except Exception as exc:
        # Retry failures must leave an inspectable artifact as well; otherwise
        # the UI reports an error but the last successful/partial content is lost.
        partial=parent_job.get('result') or {'results':[]}
        partial=dict(partial)
        partial['runId']=str(uuid.uuid4())
        partial['createdAt']=datetime.now(timezone.utc).isoformat()
        partial['status']='cancelled_partial' if JOBS.get(job_id, {}).get('cancelRequested') else 'error_partial'
        if partial['status']=='cancelled_partial':
            partial['message']='사용자 요청으로 회귀 재작성을 중단했습니다. 완료된 결과만 저장했습니다.'
        partial['error']=str(exc)
        partial['errorType']=type(exc).__name__
        partial['errorTraceback']=traceback.format_exc()
        output_directory=None
        try: output_directory=save_result(partial)
        except Exception as save_exc: partial['saveError']=str(save_exc)
        JOBS[job_id].update(status='error',error=str(exc),errorType=type(exc).__name__,
                            errorTraceback=partial['errorTraceback'],result=partial,
                            partialResult=partial,outputDirectory=output_directory)
    finally:
        LOCK.release()

def run_validate_job(job_id, parent_job, section_id):
    try:
        kind=parent_job['result']['documentType']; plan=impact_plan(kind,section_id)
        specs={s['sectionId']:s for s in CONTRACT['documents'][kind]}
        rows={r['sectionId']:r for r in parent_job['result'].get('results',[])}
        checked=[]
        for item in plan['affected']:
            if JOBS.get(job_id, {}).get('cancelRequested'):
                raise RuntimeError('사용자가 실행을 중단했습니다.')
            spec=specs[item['sectionId']]; row=rows.get(item['sectionId'])
            if not row: continue
            content=row.get('functionOutput') or {'generatedText':row.get('generatedText',''),'tables':row.get('tables',[])}
            content_hash=_content_hash(content)
            previous=row.get('validation',{}) or {}
            if previous.get('status') in {'pass','fail'} and previous.get('contentHash')==content_hash and previous.get('policyVersion')==VALIDATION_POLICY_VERSION:
                previous['reused']=True
                row['validation']=previous
                checked.append(item['sectionId'])
                continue
            source=validation_source_for(row,content)
            result=_reconcile_validation(spec,content,py.validate_section(section_spec=spec,content=content,source_data=source))
            row['validation']=result; checked.append(item['sectionId'])
        parent_job['result']['validation1']=[{'sectionId':sid,'status':rows[sid]['validation'].get('status'),'issues':rows[sid]['validation'].get('issues',[])} for sid in checked]
        parent_job['result']['status']='validation1_failed' if any(rows[sid]['validation'].get('status')=='fail' for sid in checked) else 'validation1_passed'
        parent_job['result']['message']='선택 항목 및 연관 항목 검증 1 완료.'
        JOBS[job_id].update(status='done',result=parent_job['result'],outputDirectory=save_result(parent_job['result']),message='선택 항목 및 연관 항목 검증 1 완료',completedCalls=len(checked))
    except Exception as exc:
        partial=dict(parent_job.get('result') or {})
        partial['runId']=str(uuid.uuid4()); partial['createdAt']=datetime.now(timezone.utc).isoformat()
        partial['status']='error_partial'; partial['error']=str(exc); partial['errorType']=type(exc).__name__; partial['errorTraceback']=traceback.format_exc()
        output_directory=None
        try: output_directory=save_result(partial)
        except Exception as save_exc: partial['saveError']=str(save_exc)
        JOBS[job_id].update(status='error',error=str(exc),errorType=type(exc).__name__,errorTraceback=partial['errorTraceback'],result=partial,partialResult=partial,outputDirectory=output_directory)
    finally: LOCK.release()

def run_validate_all_job(job_id, result, skip_passed=False):
    try:
        specs={s['sectionId']:s for s in CONTRACT['documents'][result['documentType']]}
        for row in result.get('results',[]):
            if JOBS.get(job_id, {}).get('cancelRequested'):
                raise RuntimeError('사용자가 실행을 중단했습니다.')
            spec=specs.get(row['sectionId'])
            if spec and spec.get('enabled'):
                if skip_passed and row.get('validation',{}).get('status')=='pass':
                    continue
                content=row.get('functionOutput') or {'generatedText':row.get('generatedText',''),'tables':row.get('tables',[])}
                content_hash=_content_hash(content)
                previous=row.get('validation',{}) or {}
                if previous.get('status') in {'pass','fail'} and previous.get('contentHash')==content_hash and previous.get('policyVersion')==VALIDATION_POLICY_VERSION:
                    previous['reused']=True
                    row['validation']=previous
                else:
                    source=validation_source_for(row,content)
                    row['validation']=_reconcile_validation(spec,content,py.validate_section(spec,content,source))
                source=validation_source_for(row,content)
                row['evaluation']=score_section(spec,content,row['validation'],result['documentType'],source)
        result['evaluationSummary']=aggregate_scores(result.get('results',[]))
        result['validation1']=[{'sectionId':row.get('sectionId'),'status':row.get('validation',{}).get('status','not_run'),
                               'issues':row.get('validation',{}).get('issues',[]),'warnings':row.get('validation',{}).get('warnings',[]),
                               'attemptCount':len(row.get('attempts',[]))} for row in result.get('results',[]) if row.get('validation')]
        failed=any(r.get('validation',{}).get('status')=='fail' for r in result['results'])
        result['status']='validation1_failed' if failed else 'validation1_passed'
        if not failed: result['document']=py.assemble_document(result['results'],[t for r in result['results'] for t in r.get('tables',[])],[i for r in result['results'] for i in r.get('images',[])])
        result['message']=('기존 pass 항목은 건너뛰고 미통과·미검증 항목만 검증한 뒤 조립했습니다.' if skip_passed and not failed else ('전체 항목 검증 1 및 조립 완료.' if not failed else '검증 1 미통과 항목이 있어 조립을 보류했습니다.'))
        JOBS[job_id].update(status='done',result=result,outputDirectory=save_result(result),message=result['message'])
    except Exception as exc:
        partial=dict(result)
        partial['runId']=str(uuid.uuid4())
        partial['createdAt']=datetime.now(timezone.utc).isoformat()
        partial['status']='error_partial'
        partial['error']=str(exc)
        partial['errorType']=type(exc).__name__
        partial['errorTraceback']=traceback.format_exc()
        output_directory=None
        try: output_directory=save_result(partial)
        except Exception as save_exc: partial['saveError']=str(save_exc)
        JOBS[job_id].update(status='error',error=str(exc),errorType=type(exc).__name__,
                            errorTraceback=partial['errorTraceback'],result=partial,
                            partialResult=partial,outputDirectory=output_directory)
    finally: LOCK.release()

def run_image_retry_job(job_id, result, section_id):
    try:
        row=next(r for r in result.get('results',[]) if r.get('sectionId')==section_id)
        source={'item':result.get('research',{}).get('sources',[])}
        outs=[]
        for flow_type in ('USER_FLOW','SERVICE_ARCHITECTURE'):
            if JOBS.get(job_id, {}).get('cancelRequested'):
                raise RuntimeError('사용자가 실행을 중단했습니다.')
            outs.append(gpt.generate_image_spec(item=source,architecture={'design':{},'retryInstruction':'이미지 디자인만 재생성'},flow_type=flow_type))
        row['images']=[flow_image(o) for o in outs]; row['functionOutput']=outs[0]; row['imageRetry']={'flows':['USER_FLOW','SERVICE_ARCHITECTURE'],'relatedSectionsSkipped':True}
        result['message']='이미지 명세와 이미지 결과만 재생성했습니다. 연관 사업계획서 항목은 실행하지 않았습니다.'; result['runId']=str(uuid.uuid4()); result['createdAt']=datetime.now(timezone.utc).isoformat(); result['retryHistory']=list(result.get('retryHistory',[]))+[{'timestamp':result['createdAt'],'mode':'image_only','selectedSectionId':section_id,'status':result.get('status','generated')}]
        JOBS[job_id].update(status='done',result=result,outputDirectory=save_result(result),message=result['message'],completedCalls=2)
    except Exception as exc:
        partial=dict(result)
        partial['runId']=str(uuid.uuid4()); partial['createdAt']=datetime.now(timezone.utc).isoformat()
        partial['status']='error_partial'; partial['error']=str(exc); partial['errorType']=type(exc).__name__; partial['errorTraceback']=traceback.format_exc()
        output_directory=None
        try: output_directory=save_result(partial)
        except Exception as save_exc: partial['saveError']=str(save_exc)
        JOBS[job_id].update(status='error',error=str(exc),errorType=type(exc).__name__,errorTraceback=partial['errorTraceback'],result=partial,partialResult=partial,outputDirectory=output_directory)
    finally: LOCK.release()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # The browser polls /api/jobs every 1.2 seconds. Keep that transport
        # traffic out of the terminal so the actual function progress/errors
        # remain readable.
        request_line = str(args[0]) if args else ''
        if request_line.startswith('GET /api/jobs/'):
            return
        super().log_message(format, *args)

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
        if parsed.path == '/favicon.ico':
            return self.respond(204, b'', 'image/x-icon')
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
            return self.respond(200, (BASE/'app'/'strategy_writing_agent.html').read_bytes(), 'text/html; charset=utf-8')
        asset_paths = {
            '/strategy_writing_agent.css': BASE/'res'/'css'/'strategy_writing_agent.css',
            '/strategy_writing_agent.js': BASE/'res'/'js'/'strategy_writing_agent.js',
            '/res/css/strategy_writing_agent.css': BASE/'res'/'css'/'strategy_writing_agent.css',
            '/res/js/strategy_writing_agent.js': BASE/'res'/'js'/'strategy_writing_agent.js',
        }
        if parsed.path in asset_paths:
            asset = asset_paths[parsed.path]
            if asset.exists():
                content_type = 'text/css; charset=utf-8' if asset.suffix == '.css' else 'application/javascript; charset=utf-8'
                return self.respond(200, asset.read_bytes(), content_type)
            return self.respond(404, {'error':'asset not found'})
        if self.path == '/api/examples':
            files = {'general':'example_general_part2.json','pre_startup':'example_pre_startup.json','early_startup':'example_early_startup.json'}
            examples = {k: json.loads((BASE/'res/back_input'/name).read_text(encoding='utf-8')) for k,name in files.items()}
            return self.respond(200, examples)
        if parsed.path == '/api/latest-results':
            runs=BASE/'res/back_output'/'runs'; latest={}
            if runs.exists():
                for kind in KINDS:
                    matches=sorted(runs.glob(f'*_{kind}_*/result.json'),key=lambda p:p.stat().st_mtime,reverse=True)
                    if matches:
                        try:
                            latest[kind]=json.loads(matches[0].read_text(encoding='utf-8'))
                            latest[kind]['resultPath']=str(matches[0].resolve())
                            latest[kind]['outputDirectory']=str(matches[0].parent.resolve())
                        except Exception: pass
            return self.respond(200,latest)
        if self.path == '/api/section-mapping':
            mapping=json.loads((BASE/'res/back_input'/'section_mapping.json').read_text(encoding='utf-8'))
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
        if self.path not in ['/api/run','/api/retry','/api/retry-latest','/api/validate-latest','/api/validate-all-latest','/api/image-retry-latest','/api/cancel']:
            return self.respond(404, {'error':'not found'})
        acquired=False
        try:
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size <= 2_000_000:
                raise ValueError('입력 크기는 2MB 이하여야 합니다.')
            body = json.loads(self.rfile.read(size))
            if self.path == '/api/cancel':
                target=JOBS.get(body.get('jobId'))
                if not target or target.get('status')!='running':
                    return self.respond(404, {'error':'실행 중인 작업을 찾을 수 없습니다.'})
                target['cancelRequested']=True
                target['message']='사용자 중단 요청을 처리하는 중입니다.'
                return self.respond(202, {'jobId':body.get('jobId'),'message':'중단 요청을 접수했습니다.'})
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
            elif self.path == '/api/image-retry-latest':
                kind=body.get('documentType'); section_id=body.get('sectionId'); runs=BASE/'res/back_output'/'runs'; files=sorted(runs.glob(f'*_{kind}_*/result.json'),key=lambda p:p.stat().st_mtime,reverse=True)
                if not files or kind not in KINDS or section_id not in {'2.3.6','3.3.6'}: raise ValueError('이미지 사업계획서 항목과 최신 결과가 필요합니다.')
                saved=json.loads(files[0].read_text(encoding='utf-8')); JOBS[job_id]={'status':'running','message':'이미지만 재생성 중','completedCalls':0}
                threading.Thread(target=run_image_retry_job,args=(job_id,saved,section_id),daemon=True).start()
            elif self.path == '/api/validate-all-latest':
                kind=body.get('documentType'); runs=BASE/'res/back_output'/'runs'; files=sorted(runs.glob(f'*_{kind}_*/result.json'),key=lambda p:p.stat().st_mtime,reverse=True)
                if not files or kind not in KINDS: raise ValueError('최신 실행 결과와 사업계획서 유형이 필요합니다.')
                saved=json.loads(files[0].read_text(encoding='utf-8'))
                if saved.get('status')=='error_partial' or not isinstance(saved.get('results'),list) or not saved.get('results'):
                    raise ValueError('최신 결과가 부분 결과이거나 작성 항목이 없어 검증·조립할 수 없습니다. 먼저 전략·작성 실행을 완료하세요.')
                JOBS[job_id]={'status':'running','message':'전체 검증 및 조립 준비 중','completedCalls':0}
                threading.Thread(target=run_validate_all_job,args=(job_id,saved,bool(body.get('skipPassed'))),daemon=True).start()
            elif self.path == '/api/validate-latest':
                kind=body.get('documentType'); section_id=body.get('sectionId'); runs=BASE/'res/back_output'/'runs'; files=sorted(runs.glob(f'*_{kind}_*/result.json'),key=lambda p:p.stat().st_mtime,reverse=True)
                if not files or kind not in KINDS or not isinstance(section_id,str): raise ValueError('최신 실행 결과와 사업계획서 항목 위치가 필요합니다.')
                saved=json.loads(files[0].read_text(encoding='utf-8')); parent={'result':saved}; plan=impact_plan(kind,section_id)
                JOBS[job_id]={'status':'running','message':'선택 항목 및 연관 항목 검증 준비 중','completedCalls':0,'impact':plan}
                threading.Thread(target=run_validate_job,args=(job_id,parent,section_id),daemon=True).start()
            elif self.path == '/api/retry-latest':
                kind=body.get('documentType'); section_id=body.get('sectionId'); runs=BASE/'res/back_output'/'runs'; files=sorted(runs.glob(f'*_{kind}_*/result.json'),key=lambda p:p.stat().st_mtime,reverse=True)
                if not files or kind not in KINDS or not isinstance(section_id,str): raise ValueError('최신 실행 결과와 사업계획서 항목 위치가 필요합니다.')
                saved=json.loads(files[0].read_text(encoding='utf-8')); back=json.loads((BASE/'res/back_input'/{'general':'example_general_part2.json','pre_startup':'example_pre_startup.json','early_startup':'example_early_startup.json'}[kind]).read_text(encoding='utf-8')); parent={'result':saved,'_input':normalize_back_input(back,kind)}
                plan=impact_plan(kind,section_id); JOBS[job_id]={'status':'running','message':'최신 저장 결과 기준 재작성 준비 중','completedCalls':0,'_input':parent['_input'],'_parentJobId':'latest','impact':plan}
                threading.Thread(target=run_retry_job,args=(job_id,parent,section_id,body.get('instruction',''),body.get('mode','manual')),daemon=True).start()
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

