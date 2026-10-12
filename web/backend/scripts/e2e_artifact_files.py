"""산출물 파일 흐름을 실제 서버 · 워커 · MySQL로 끝까지 확인한다 (SB-295 · SB-320).

    python scripts/e2e_artifact_files.py --url mysql+pymysql://root:sbrain-test@127.0.0.1:3307/sbrain_e2e?charset=utf8mb4

e2e_failure_resume.py처럼 워커를 이 프로세스 안에서 돌린다(따로 띄운 워커가 있으면 끈다). 산출물 파일은 오케스트레이터의 파일 저장소
(`SBRAIN_ARTIFACT_ROOT`, 이 스크립트가 임시 폴더로 잡는다 — 웹과 워커가 같은 폴더를 본다)에 있고, 웹은 결과의 파일 참조 key로
read_artifact_file을 불러 내려 준다(SB-311). 워커의 스텁 구현 Agent는 작은 자리채움 파일(index.html · onepage.svg · infographic.svg(웹개발 · AI API도 SVG — 오케스트레이터 2026-10-11) ·
README.md · plan.docx)을 만든다 — 이 스크립트는 "웹 ↔ 파일 저장소 배관"을 확인하며 파일 내용의 품질은 보지 않는다.
조율 T-C1 · T-C3는 평소처럼 실제 LLM이라 OPENAI_API_KEY(agent-orchestration/.env)가 필요하다.
`E2E_STUB_PARTNER=1`을 주면 전략 · 작성 · 검증-1도 스텁이라 실제 OpenAI는 T-C1 · T-C3 몇 번만 부른다(e2e_worker_flow.use_stub_partner_agents).

차례대로:
  1. 웹개발     프로젝트 → 화면 8. 결과의 두 경로가 key 기반 웹 주소이고 받으면 저장소 파일과 바이트가 같다 · 헤더
  2. 접근 제한  비로그인 401 · 다른 계정 404 · 관리자 404 · 바꾼 key · 경로 이동 시도 404
  3. 재작성     실행 파일 재작성 → 전후 주소가 서로 다름 · 이전 파일도 계속 받을 수 있음
  4. 묶음 zip   표현 검수까지 마친 뒤 결과물 zip: 프로토타입 · 인포그래픽 파일과, 계획서(planDoc)로 웹이 만든 진짜 .docx(SB-341), 계획서 그림의 원본 SVG와 docx 안의 그림(SB-340)이 들어 있음
  5. 영구 삭제  삭제 대기열에 줄이 생기고(관리자 목록) 주소가 404 · 워커가 처리하면 파일이 지워짐
  6. 원페이지   두 참조가 같은 onepage.svg — 인포그래픽 주소만 보이고 실행 경로는 없음
  7. 탈퇴       탈퇴 뒤 주소가 404 · 삭제 대기열에 줄이 더 생김
"""
import argparse
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from docx import Document

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e2e_worker_flow import DEFAULT_URL, FULL_INPUT, PROFILE, configure_env  # noqa: E402

results: list[tuple[str, bool, str]] = []
if hasattr(sys.stdout, 'reconfigure'):  # 콘솔 인코딩(cp949 등)에 없는 문자(— 등)가 있어도 출력이 죽지 않게
    sys.stdout.reconfigure(errors='replace')


def step(name: str, ok: bool, detail: str = '') -> bool:
    results.append((name, ok, detail))
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f' — {detail}' if detail else ''), flush=True)
    return ok


class Abort(Exception):
    """이어갈 수 없는 실패."""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', default=DEFAULT_URL)
    parser.add_argument('--wait-sec', type=float, default=240, help='상태가 바뀌길 기다리는 최대 시간(초, 기본 240)')
    args = parser.parse_args()

    configure_env(args.url)
    artifact_dir = tempfile.mkdtemp(prefix='e2e_artifacts_')
    os.environ['SBRAIN_ARTIFACT_ROOT'] = artifact_dir  # 웹 조립과 워커 조립이 모두 읽는다 — 앱을 가져오기 전에 잡는다
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    print(f'파일 저장소(임시): {artifact_dir}', flush=True)

    from fastapi.testclient import TestClient
    from sbrain.bootstrap import build_app
    from sbrain.orchestrator.file_deletion import process_file_deletions
    from sbrain.worker import Worker, WorkerConfig

    import app.routers.auth as auth_router
    import app.routers.projects as projects
    import app.security as security
    from app.database import SessionLocal
    from app.main import app
    from app.models import User
    from app.orch import get_gateway

    projects.ORCH_WAIT_TIMEOUT_SEC = 5.0
    root = Path(artifact_dir)

    worker_app = build_app()
    worker = Worker(worker_app, WorkerConfig(poll_sec=0.3, threads=2, lease_sec=60), log=lambda line: None)
    worker_thread = threading.Thread(target=worker.run, name='e2e-worker', daemon=True)
    worker_thread.start()

    category = {'value': None}
    spec = worker_app.registry.get('T-C1')
    original_tc1 = spec.fn

    def forced_tc1(*a, **kw):  # 시험이 카테고리를 고르도록 조율 T-C1의 결과 카테고리만 바꾼다(LLM 호출은 그대로)
        out = original_tc1(*a, **kw)
        if not category['value']:
            return out
        return out.model_copy(update={'category': category['value'],
                                      'item_spec': out.item_spec.model_copy(update={'category': category['value']})})

    spec.fn = forced_tc1

    def j(res):
        try:
            return res.json()
        except Exception:
            return {'raw': res.text[:300]}

    who = {'email': 'owner@example.com'}
    security.verify_google_id_token = lambda t: {'sub': 'sub-' + who['email'], 'email': who['email'], 'name': 'E2E'}
    auth_router.verify_google_id_token = security.verify_google_id_token

    def sign_in(client: TestClient, email: str, with_profile: bool = True) -> None:
        who['email'] = email
        res = client.post('/auth/google', json={'id_token': 'x', 'aiTrainingAgreed': True, 'notifyAgreed': True})
        if res.status_code != 200:
            raise Abort(f'로그인 실패 {email}: {res.status_code} {j(res)}')
        client.patch('/auth/consent', json={'termsAgreed': True, 'privacyAgreed': True, 'ageConfirmed': True})
        if with_profile:
            res = client.post('/profile', json=PROFILE)
            if res.status_code != 201:
                raise Abort(f'프로필 저장 실패 {email}: {res.status_code} {j(res)}')

    def wait_for(label: str, cond, interval: float = 0.5):
        deadline = time.time() + args.wait_sec
        while time.time() < deadline:
            value = cond()
            if value:
                return value
            time.sleep(interval)
        raise Abort(f'{label}: {args.wait_sec:.0f}초 안에 되지 않음 — 워커가 도는지 확인하세요')

    try:
        with TestClient(app) as owner:
            def drive_to_artifact_review(cat: str | None) -> int:
                """프로젝트 생성 → 공고 선택 → 계획서 → 프로토타입 → 화면 8(산출물 확인) 대기."""
                category['value'] = cat
                res = owner.post('/projects', data={'payload': json.dumps(FULL_INPUT)})
                if res.status_code != 201:
                    raise Abort(f'프로젝트 생성 실패 {res.status_code} {j(res)}')
                pid = j(res)['project_id']
                cands = wait_for('공고 후보', lambda: (lambda b: b if b.get('status') != 'pending' else None)(
                    j(owner.get(f'/projects/{pid}/match-candidates'))))
                if cands.get('status') != 'ready' or not cands.get('candidates'):
                    raise Abort(f'공고 후보 없음 {cands.get("status")} {cands.get("message")}')
                blocked = set(cands.get('blocked_notice_ids') or [])
                for cand in [c for c in cands['candidates'] if c['notice_id'] not in blocked][:3]:
                    body = j(owner.post(f'/projects/{pid}/generate', json={'notice_id': cand['notice_id']}))
                    if body.get('status') == 'pending':
                        body = wait_for('자격 확인', lambda: (lambda b: b if b.get('status') != 'pending' else None)(
                            j(owner.get(f'/projects/{pid}/eligibility'))))
                    if body.get('status') == 'ready' and (body.get('eligibility') or {}).get('passed'):
                        break
                else:
                    raise Abort('자격을 통과한 공고를 고르지 못함')

                def reach(label: str, stage: str) -> None:
                    def cond():
                        body = j(owner.get(f'/projects/{pid}/status'))
                        if body.get('match_status') in ('failed', 'halted'):
                            raise Abort(f'{label} 실패 {body}')
                        return body.get('stage') == stage and body.get('match_status') == 'user_waiting'
                    wait_for(label, cond)

                owner.post(f'/projects/{pid}/plan/start')
                reach('계획서 작성', 'plan_review_pending')
                owner.post(f'/projects/{pid}/prototype/start')
                reach('프로토타입 제작', 'artifact_review')
                return pid

            def artifact_of(pid: int) -> dict:
                arts = (j(owner.get(f'/projects/{pid}/result')).get('plan') or {}).get('artifacts') or []
                return arts[0] if arts else {}

            def key_of(pid: int, url: str | None) -> str:
                """결과의 파일 주소에서 key(저장소 안 위치)를 읽는다 — 이 스크립트만 저장소 파일과 비교하려고 쓴다. 웹은 key를 풀지 않는다."""
                prefix = f'/projects/{pid}/artifact-files/'
                return url[len(prefix):] if url and url.startswith(prefix) else ''

            def deletions(admin_client: TestClient) -> list[dict]:
                return j(admin_client.get('/admin/file-deletions?limit=200'))

            try:
                sign_in(owner, 'owner@example.com')
                step('로그인 · 프로필', True)
                admin = TestClient(app)
                sign_in(admin, 'admin@example.com', with_profile=False)
                with SessionLocal() as db:
                    db.query(User).filter(User.email == 'admin@example.com').update({'role': 'admin'})
                    db.commit()

                # 1) 웹개발 — 결과의 주소와 내려받기
                pid = drive_to_artifact_review('웹개발')
                art = artifact_of(pid)
                step('1. 화면 8: 웹개발 산출물', art.get('category') == 'webdev', f"category={art.get('category')}")
                exec_url, info_url = art.get('executable_path'), art.get('infographic_path')
                exec_key, info_key = key_of(pid, exec_url), key_of(pid, info_url)
                step('1. 결과의 두 경로가 key 기반 웹 주소(SB-314)',
                     exec_key.endswith('/index.html') and info_key.endswith('/infographic.svg'), f'실행={exec_url} 인포그래픽={info_url}')

                html = owner.get(exec_url)
                stored = (root / exec_key)
                step('1. index.html 내려받기 — 저장소 파일과 바이트가 같음',
                     html.status_code == 200 and stored.is_file() and html.content == stored.read_bytes() and len(html.content) > 0,
                     f"{html.status_code} {len(html.content)}바이트 저장소 파일 있음={stored.is_file()}")
                csp = html.headers.get('content-security-policy', '')
                step('1. index.html 헤더(타입 · nosniff · no-store · 샌드박스 CSP)',
                     html.headers.get('content-type', '').startswith('text/html')
                     and html.headers.get('x-content-type-options') == 'nosniff'
                     and html.headers.get('cache-control') == 'private, no-store'
                     and 'sandbox allow-scripts' in csp and 'allow-same-origin' not in csp,
                     f"{html.headers.get('content-type')} / {csp[:60]}")
                img = owner.get(info_url)
                step('1. 인포그래픽 내려받기 — 저장소 파일과 바이트가 같고 형식은 오케스트레이터가 기록한 값',
                     img.status_code == 200 and img.headers.get('content-type') == 'image/svg+xml'
                     and (root / info_key).is_file() and img.content == (root / info_key).read_bytes(),
                     f"{img.status_code} {img.headers.get('content-type')} {len(img.content)}바이트")

                # 2) 접근 제한
                anon = TestClient(app)
                res = anon.get(exec_url)
                step('2. 비로그인은 401', res.status_code == 401, f'{res.status_code}')
                other = TestClient(app)
                sign_in(other, 'other@example.com', with_profile=False)
                res = other.get(exec_url)
                step('2. 다른 계정은 404(파일이 있는지 알 수 없음)', res.status_code == 404, f'{res.status_code} {j(res).get("code")}')
                res = admin.get(exec_url)
                step('2. 관리자도 404(기획서 6-7: 산출물 내용은 소유자만)', res.status_code == 404, f'{res.status_code}')
                run_id, execution_id, unique, name = exec_key.split('/')
                bad = [f'/projects/{pid}/artifact-files/{run_id}/{"0" * 12}/{unique}/{name}',
                       f'/projects/{pid}/artifact-files/{run_id}/{execution_id}/{unique}/secret.txt',
                       f'/projects/{pid}/artifact-files/{run_id}/{execution_id}/{unique}/..%2f..%2f..%2fapp%2fmain.py',
                       f'/projects/{pid}/artifact-files/..%2f{run_id}/{execution_id}/{unique}/{name}',
                       f'/projects/{pid}/artifact-files/{run_id}/{execution_id}/{unique}']
                codes = [owner.get(u).status_code for u in bad]
                step('2. 없는 key · 경로를 벗어나는 요청은 404', all(c == 404 for c in codes), f'{codes}')
                step('2. 다른 프로젝트 번호로 같은 key를 요청해도 404', owner.get(f'/projects/{pid + 9999}/artifact-files/{exec_key}').status_code == 404)

                # 3) 실행 파일 재작성 → 새 파일
                res = owner.post(f'/projects/{pid}/retry-task', json={'task_key': 'implement_prototype'})
                acc = j(res)
                step('3. 실행 파일 재작성 요청', res.status_code == 200, f"{res.status_code} cycle={acc.get('cycle_id')} screen={acc.get('screen')} {acc.get('detail') or ''}")
                if res.status_code == 200:
                    rr = wait_for('재작성', lambda: (lambda b: b if b.get('status') in ('완료', '실패') else None)(
                        j(owner.get(f'/projects/{pid}/rework-result'))), interval=1.0)
                    step('3. 재작성 완료', rr.get('status') == '완료', f"status={rr.get('status')} kept={rr.get('kept')}")
                    proto = next((f for f in (rr.get('files') or []) if f.get('artifact') == 'prototype'), {})
                    before, after = proto.get('before_path') or '', proto.get('after_path') or ''
                    step('3. 재작성 결과의 전후 경로가 서로 다른 key 기반 주소',
                         key_of(pid, before).endswith('/index.html') and key_of(pid, after).endswith('/index.html') and before != after,
                         f'전={before[-48:]} 후={after[-48:]}')
                    step('3. changed.executable_path도 같은 주소',
                         (rr.get('changed') or {}).get('executable_path') == {'before': before, 'after': after})
                    old_res, new_res = owner.get(before), owner.get(after)
                    step('3. 이전 · 새 파일을 둘 다 받을 수 있음(이전 파일은 남는다)',
                         old_res.status_code == 200 and new_res.status_code == 200, f'{old_res.status_code} / {new_res.status_code}')
                    step('3. 결과의 실행 경로는 유지된 쪽(kept)을 가리킴',
                         artifact_of(pid).get('executable_path') == (after if rr.get('kept') == '후' else before),
                         f"kept={rr.get('kept')}")

                # 4) 종합 평가 · 표현 검수를 마친 뒤 결과물 zip
                res = owner.post(f'/projects/{pid}/final-review/start')
                step('4. 종합 평가로 진행(8→9)', res.status_code == 200, f'{res.status_code}')
                res = owner.post(f'/projects/{pid}/review/start')
                if res.status_code == 409 and (j(res).get('detail') or {}).get('confirmation_required'):
                    res = owner.post(f'/projects/{pid}/review/start', json={'confirmed': True})
                step('4. 표현 검수 시작', res.status_code == 200, f'{res.status_code}')
                wait_for('표현 검수', lambda: (lambda b: b.get('stage') == 'done' and b.get('match_status') == 'completed')(
                    j(owner.get(f'/projects/{pid}/status'))))
                res = owner.get(f'/projects/{pid}/deliverable.zip')
                names = []
                try:
                    archive = zipfile.ZipFile(io.BytesIO(res.content))
                    names = archive.namelist()
                    intact = archive.testzip() is None
                    # 계획서는 파일 참조(스텁은 자리채움 파일)가 아니라 planDoc으로 웹이 만든 진짜 .docx다(SB-341)
                    plan_bytes = archive.read('plan/business-plan.docx') if 'plan/business-plan.docx' in names else b''
                    docx_ok = plan_bytes[:2] == b'PK' and len(Document(io.BytesIO(plan_bytes)).paragraphs) > 0
                    diagram_svgs = sorted(n for n in names if n.startswith('plan/diagrams/'))
                    diagram_pictures = len(Document(io.BytesIO(plan_bytes)).inline_shapes) if plan_bytes else 0
                except zipfile.BadZipFile:
                    intact = docx_ok = False
                    diagram_svgs, diagram_pictures = [], 0
                step('4. 결과물 zip 내려받기(SB-316)', res.status_code == 200 and res.headers.get('content-type') == 'application/zip' and intact,
                     f"{res.status_code} 파일 {names}")
                step('4. zip에 계획서 · 프로토타입 · 인포그래픽이 들어 있음',
                     'plan/business-plan.docx' in names and 'plan/plan.docx' not in names and 'prototype/index.html' in names
                     and 'infographic/infographic.svg' in names and docx_ok,
                     f'business-plan.docx가 열리는 진짜 docx={docx_ok} 파일={sorted(names)}')
                # 계획서 그림(SB-340): 계획서(planDoc)의 그림 SVG 원본이 plan/diagrams/에 들고, docx 안에 같은 수의 그림(PNG)이 들어 있다.
                # 결과물의 인포그래픽(기준 문서 T-C4)도 docx에 그림으로 들어가지만 원본은 infographic/에만 있다 — 그래서 docx 그림 = 계획서 그림 + 인포그래픽 1
                step('4. 계획서 그림 · 인포그래픽 — 원본 SVG가 plan/diagrams/ · infographic/에 있고 docx 안에 그만큼 그림이 있음',
                     len(diagram_svgs) >= 1 and diagram_pictures == len(diagram_svgs) + 1,
                     f'SVG={diagram_svgs} + infographic 1 docx 그림={diagram_pictures}')
                step('4. 비로그인 · 다른 계정은 zip도 받지 못함',
                     anon.get(f'/projects/{pid}/deliverable.zip').status_code == 401
                     and other.get(f'/projects/{pid}/deliverable.zip').status_code == 404)

                # 5) 영구 삭제 → 삭제 대기열 → 워커가 지움
                get_gateway()._orch.store.file_deletion_delay_sec = 0  # 웹 조립의 대기열 지연(10분)을 이 시험에서만 없앤다
                queued_before = len(deletions(admin))
                step('5. 삭제 전: 대기열이 비어 있음', queued_before == 0, f'{queued_before}줄')
                res = owner.delete(f'/projects/{pid}/permanent')
                step('5. 영구 삭제 204', res.status_code == 204, f'{res.status_code} {j(res) if res.status_code != 204 else ""}')
                rows = deletions(admin)
                step('5. 관리자 대기열에 줄이 생김(상태 대기, 이름 · 키는 없음)',
                     len(rows) >= 1 and all(r['status'] == '대기' for r in rows)
                     and all(not ({'key', 'key_prefix', 'name'} & set(r)) for r in rows), f'{len(rows)}줄 {[r["status"] for r in rows]}')
                step('5. 지운 뒤 주소는 404', owner.get(exec_url).status_code == 404)
                summary = process_file_deletions(worker_app.store, worker_app.engine.files)
                step('5. 워커가 대기열을 처리하면 저장소의 그 실행 건 파일이 지워짐',
                     not (root / run_id).exists() and not deletions(admin),
                     f'처리 결과={summary} 남은 폴더={sorted(p.name for p in root.iterdir())} 남은 줄={len(deletions(admin))}')

                # 6) 원페이지 — 두 참조가 같은 onepage.svg
                pid2 = drive_to_artifact_review('원페이지')
                art2 = artifact_of(pid2)
                one_url = art2.get('infographic_path')
                one_key = key_of(pid2, one_url)
                step('6. 화면 8: 원페이지 산출물', art2.get('category') == 'onepage', f"category={art2.get('category')}")
                step('6. 인포그래픽 경로가 onepage.svg 주소이고 실행 경로는 없음',
                     one_key.endswith('/onepage.svg') and art2.get('executable_path') is None,
                     f"인포그래픽={one_url} 실행={art2.get('executable_path')}")
                one = owner.get(one_url)
                step('6. onepage.svg 내려받기 — 저장소 파일과 바이트가 같음',
                     one.status_code == 200 and one.headers.get('content-type') == 'image/svg+xml'
                     and (root / one_key).is_file() and one.content == (root / one_key).read_bytes(),
                     f"{one.status_code} {one.headers.get('content-type')} {len(one.content)}바이트")

                # 7) 탈퇴
                res = owner.delete('/auth/me')
                step('7. 탈퇴 204', res.status_code == 204, f'{res.status_code} {j(res) if res.status_code != 204 else ""}')
                rows = deletions(admin)
                step('7. 탈퇴 뒤 삭제 대기열에 줄이 생김', len(rows) >= 1, f'{len(rows)}줄')
                process_file_deletions(worker_app.store, worker_app.engine.files)
                left = [p.name for p in root.iterdir()]
                step('7. 워커가 처리하면 저장소에 우리 파일이 남지 않음', not left and not deletions(admin), f'남은 항목={left}')
            except Abort as exc:
                step('중단', False, str(exc))
            except Exception as exc:  # noqa: BLE001 - 점검 도구라 어떤 오류든 기록한다
                step('예상 못 한 오류', False, f'{type(exc).__name__}: {str(exc)[:300]}')
    finally:
        worker.stop()
        worker_thread.join(timeout=60)
        shutil.rmtree(artifact_dir, ignore_errors=True)

    failed = [r for r in results if not r[1]]
    print(f'\n요약: {len(results) - len(failed)}/{len(results)} 통과' + (f', 실패: {[r[0] for r in failed]}' if failed else ''))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
