"""샘플 산출물(반찬온)로 산출물 파일 흐름을 실제 서버 · 워커 · MySQL로 끝까지 확인한다 (SB-295).

    python scripts/e2e_artifact_files.py --url mysql+pymysql://root:sbrain-test@127.0.0.1:3307/sbrain_e2e?charset=utf8mb4
    python scripts/e2e_artifact_files.py --samples C:\\path\\산출물샘플_반찬온.zip

e2e_failure_resume.py처럼 워커를 이 프로세스 안에서 돌린다(따로 띄운 워커가 있으면 끈다). 스텁 Agent는 파일을 만들지 않으므로
스텁 T-B1 · T-B2 · M-2를 감싸서 **구현 Agent가 하기로 합의한 대로** 저장 폴더(`ARTIFACT_DIR`, 이 스크립트가 임시 폴더로 잡는다)에
`<project_id>/<시도 ID>/<파일>`로 샘플 파일을 쓰고 상대 경로를 돌려준다(시도 ID는 호출마다 새 무작위 값).
샘플: 산출물샘플_반찬온.zip — index.html · 웹개발 SVG(infographic.svg) · 원페이지 SVG(onepage.svg). 파일 이름은 끝 글자로 가린다.
조율 T-C1 · T-C3는 평소처럼 실제 LLM이라 OPENAI_API_KEY(agent-orchestration/.env)가 필요하다.

차례대로:
  1. 웹개발     프로젝트 → 화면 8. 결과의 두 경로가 웹 주소로 바뀌어 있고(SB-293) 받으면 샘플과 바이트가 같다(SB-292) · 헤더
  2. 접근 제한  비로그인 401 · 다른 계정 404 · 관리자 404 · 이름 · 경로 이동 시도 404
  3. 재작성     실행 파일 재작성 → 새 시도 폴더 · 재작성 결과의 전후 주소가 주소로 바뀜 · 이전 시도 파일도 계속 받을 수 있음
  4. 영구 삭제  프로젝트 폴더가 지워지고 주소가 404 (SB-294)
  5. 원페이지   두 경로가 같은 onepage.svg — 인포그래픽 주소만 보이고 실행 경로는 없음 · 샘플과 바이트가 같음
  6. 탈퇴       계정의 모든 프로젝트 폴더가 지워짐 · 고아 청소는 프로젝트 행이 없는 숫자 폴더만 지움
"""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e2e_worker_flow import DEFAULT_URL, FULL_INPUT, PROFILE, configure_env  # noqa: E402

DEFAULT_SAMPLES = r'C:\Users\hjwon\Downloads\산출물샘플_반찬온.zip'
results: list[tuple[str, bool, str]] = []
if hasattr(sys.stdout, 'reconfigure'):  # 콘솔 인코딩(cp949 등)에 없는 문자(— 등)가 있어도 출력이 죽지 않게
    sys.stdout.reconfigure(errors='replace')


def step(name: str, ok: bool, detail: str = '') -> bool:
    results.append((name, ok, detail))
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f' — {detail}' if detail else ''), flush=True)
    return ok


class Abort(Exception):
    """이어갈 수 없는 실패."""


def load_samples(path: str) -> dict[str, bytes]:
    """zip(또는 폴더)에서 세 샘플을 읽는다. 이름이 index.html · 웹개발.svg · 원페이지.svg로 끝나는 파일."""
    wanted = {'index.html': 'index.html', '웹개발.svg': 'infographic.svg', '원페이지.svg': 'onepage.svg'}
    found: dict[str, bytes] = {}
    if os.path.isdir(path):
        entries = [(p.name, p.read_bytes()) for p in Path(path).iterdir() if p.is_file()]
    else:
        with zipfile.ZipFile(path) as z:
            entries = [(i.filename, z.read(i)) for i in z.infolist() if not i.is_dir()]
    for name, data in entries:
        for suffix, target in wanted.items():
            if name.endswith(suffix):
                found[target] = data
    missing = set(wanted.values()) - set(found)
    if missing:
        raise SystemExit(f'샘플에서 {sorted(missing)} 를 찾지 못했습니다: {path}')
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', default=DEFAULT_URL)
    parser.add_argument('--samples', default=DEFAULT_SAMPLES, help='샘플 zip 또는 폴더')
    parser.add_argument('--wait-sec', type=float, default=240, help='상태가 바뀌길 기다리는 최대 시간(초, 기본 240)')
    args = parser.parse_args()

    samples = load_samples(args.samples)
    configure_env(args.url)
    artifact_dir = tempfile.mkdtemp(prefix='e2e_artifacts_')
    os.environ['ARTIFACT_DIR'] = artifact_dir  # 앱을 가져오기 전에 — artifact_store가 읽는다
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    print(f'저장 폴더(임시): {artifact_dir}', flush=True)

    from fastapi.testclient import TestClient
    from sbrain.bootstrap import build_app
    from sbrain.worker import Worker, WorkerConfig

    import app.routers.auth as auth_router
    import app.routers.projects as projects
    import app.security as security
    from app import artifact_store
    from app.database import SessionLocal
    from app.main import app
    from app.models import Project, User

    assert os.path.realpath(artifact_store.ARTIFACT_DIR) == os.path.realpath(artifact_dir), '저장 폴더가 바뀌지 않았다'
    projects.ORCH_WAIT_TIMEOUT_SEC = 5.0
    root = Path(artifact_dir)

    worker_app = build_app()
    worker = Worker(worker_app, WorkerConfig(poll_sec=0.3, threads=2, lease_sec=60), log=lambda line: None)
    worker_thread = threading.Thread(target=worker.run, name='e2e-worker', daemon=True)
    worker_thread.start()

    # ── 스텁 Agent를 감싸 구현 Agent처럼 파일을 쓴다 ─────────────────────────────────────
    state = {'pid': None, 'category': None, 'written': []}

    def write_artifact(filename: str) -> str:
        attempt = uuid.uuid4().hex
        folder = root / str(state['pid']) / attempt
        folder.mkdir(parents=True)
        (folder / filename).write_bytes(samples[filename])
        state['written'].append((state['pid'], attempt, filename))
        return f"{state['pid']}/{attempt}/{filename}"

    def wrap(task_id: str, after):
        spec = worker_app.registry.get(task_id)
        original = spec.fn
        spec.fn = lambda *a, **kw: after(original(*a, **kw), *a)

    def after_tc1(out, *_):
        if not state['category']:
            return out
        return out.model_copy(update={'category': state['category'],
                                      'item_spec': out.item_spec.model_copy(update={'category': state['category']})})

    def after_tb1(out, *_):
        path = write_artifact('index.html')
        return out.model_copy(update={'entry_file_path': path,
                                      'prototype': out.prototype.model_copy(update={'entry_file_path': path})})

    def after_tb2(out, inp, *_):
        path = write_artifact('onepage.svg' if inp.category == '원페이지' else 'infographic.svg')
        return out.model_copy(update={'infographic': out.infographic.model_copy(update={'image_path': path, 'format': 'svg'})})

    def after_m2(out, inp, *_):  # 원페이지는 인포그래픽과 프로토타입이 같은 onepage.svg
        path = inp.infographic.image_path
        return out.model_copy(update={'prototype': out.prototype.model_copy(update={'entry_file_path': path, 'asset_paths': [path]})})

    wrap('T-C1', after_tc1)
    wrap('T-B1', after_tb1)
    wrap('T-B2', after_tb2)
    wrap('M-2', after_m2)

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
            def drive_to_artifact_review(category: str | None) -> int:
                """프로젝트 생성 → 공고 선택 → 계획서 → 프로토타입 → 화면 8(산출물 확인) 대기."""
                state['category'] = category
                res = owner.post('/projects', data={'payload': json.dumps(FULL_INPUT)})
                if res.status_code != 201:
                    raise Abort(f'프로젝트 생성 실패 {res.status_code} {j(res)}')
                pid = j(res)['project_id']
                state['pid'] = pid
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

            def url_pattern(pid: int, filename: str) -> re.Pattern:
                return re.compile(rf'^/projects/{pid}/artifact-files/[0-9a-f]{{32}}/{re.escape(filename)}$')

            try:
                sign_in(owner, 'owner@example.com')
                step('로그인 · 프로필', True)

                # 1) 웹개발 — 결과의 경로와 내려받기
                pid = drive_to_artifact_review('웹개발')
                art = artifact_of(pid)
                step('1. 화면 8: 웹개발 산출물', art.get('category') == 'webdev', f"category={art.get('category')}")
                exec_url, info_url = art.get('executable_path'), art.get('infographic_path')
                step('1. 결과의 두 경로가 웹 주소(SB-293)',
                     bool(url_pattern(pid, 'index.html').match(exec_url or '')) and bool(url_pattern(pid, 'infographic.svg').match(info_url or '')),
                     f'실행={exec_url} 인포그래픽={info_url}')
                step('1. 파일이 합의된 구조로 저장됨(project_id/시도 ID/파일)',
                     sorted(p.name for p in root.glob(f'{pid}/*/*')) == ['index.html', 'infographic.svg'],
                     str(sorted(str(p.relative_to(root)) for p in root.glob(f'{pid}/*/*'))))

                html = owner.get(exec_url)
                step('1. index.html 내려받기 — 샘플과 바이트가 같음',
                     html.status_code == 200 and html.content == samples['index.html'],
                     f"{html.status_code} {len(html.content)}바이트(샘플 {len(samples['index.html'])})")
                step('1. index.html 헤더(타입 · nosniff · no-store · 샌드박스 CSP)',
                     html.headers.get('content-type') == 'text/html; charset=utf-8'
                     and html.headers.get('x-content-type-options') == 'nosniff'
                     and html.headers.get('cache-control') == 'private, no-store'
                     and 'sandbox allow-scripts' in html.headers.get('content-security-policy', '')
                     and 'allow-same-origin' not in html.headers.get('content-security-policy', ''),
                     f"{html.headers.get('content-type')} / {html.headers.get('content-security-policy', '')[:60]}")
                svg = owner.get(info_url)
                step('1. 웹개발 SVG 내려받기 — 샘플과 바이트가 같음(2.4MB대)',
                     svg.status_code == 200 and svg.content == samples['infographic.svg'] and svg.headers.get('content-type') == 'image/svg+xml',
                     f"{svg.status_code} {len(svg.content)}바이트(샘플 {len(samples['infographic.svg'])}) {svg.headers.get('content-type')}")

                # 2) 접근 제한
                anon = TestClient(app)
                res = anon.get(exec_url)
                step('2. 비로그인은 401', res.status_code == 401, f'{res.status_code}')
                other = TestClient(app)
                sign_in(other, 'other@example.com', with_profile=False)
                res = other.get(exec_url)
                step('2. 다른 계정은 404(파일이 있는지 알 수 없음)', res.status_code == 404, f'{res.status_code} {j(res).get("detail")}')
                admin = TestClient(app)
                sign_in(admin, 'admin@example.com', with_profile=False)
                with SessionLocal() as db:
                    db.query(User).filter(User.email == 'admin@example.com').update({'role': 'admin'})
                    db.commit()
                res = admin.get(exec_url)
                step('2. 관리자도 404(기획서 6-7: 산출물 내용은 소유자만)', res.status_code == 404, f'{res.status_code}')
                attempt = exec_url.split('/')[4]
                bad = [f'/projects/{pid}/artifact-files/{attempt}/secret.txt',
                       f'/projects/{pid}/artifact-files/{attempt}/index.HTML',
                       f'/projects/{pid}/artifact-files/{attempt}/..%2f..%2f..%2fapp%2fmain.py',
                       f'/projects/{pid}/artifact-files/..%2f{pid}%2f{attempt}/index.html',
                       f'/projects/{pid}/artifact-files/{"0" * 32}/index.html']
                codes = [owner.get(u).status_code for u in bad]
                step('2. 허용 이름이 아니거나 경로를 벗어나는 요청은 404', all(c == 404 for c in codes), f'{codes}')

                # 3) 실행 파일 재작성 → 새 시도 폴더
                res = owner.post(f'/projects/{pid}/retry-task', json={'task_key': 'implement_prototype'})
                acc = j(res)
                step('3. 실행 파일 재작성 요청', res.status_code == 200, f"{res.status_code} cycle={acc.get('cycle_id')} screen={acc.get('screen')} {acc.get('detail') or ''}")
                if res.status_code == 200:
                    rr = wait_for('재작성', lambda: (lambda b: b if b.get('status') in ('완료', '실패') else None)(
                        j(owner.get(f'/projects/{pid}/rework-result'))), interval=1.0)
                    step('3. 재작성 완료', rr.get('status') == '완료', f"status={rr.get('status')} kept={rr.get('kept')}")
                    files = rr.get('files') or []
                    proto = next((f for f in files if f.get('artifact') == 'prototype'), {})
                    before, after = proto.get('before_path') or '', proto.get('after_path') or ''
                    pattern = url_pattern(pid, 'index.html')
                    step('3. 재작성 결과의 전후 경로가 주소이고 시도 폴더가 서로 다름(SB-293)',
                         bool(pattern.match(before)) and bool(pattern.match(after)) and before != after,
                         f'전={before} 후={after}')
                    step('3. changed.executable_path도 같은 주소',
                         (rr.get('changed') or {}).get('executable_path') == {'before': before, 'after': after})
                    old_res, new_res = owner.get(before), owner.get(after)
                    step('3. 이전 시도 · 새 시도 파일을 둘 다 받을 수 있음(이전 파일은 남는다)',
                         old_res.status_code == 200 and new_res.status_code == 200
                         and old_res.content == new_res.content == samples['index.html'],
                         f'{old_res.status_code} / {new_res.status_code}')
                    now_art = artifact_of(pid)
                    step('3. 결과의 실행 경로는 유지된 쪽(kept)을 가리킴',
                         now_art.get('executable_path') == (after if rr.get('kept') == '후' else before),
                         f"kept={rr.get('kept')} 결과 실행 경로={now_art.get('executable_path')}")
                    step('3. 시도 폴더가 늘어남(첫 시도 + 재작성)', len(list((root / str(pid)).iterdir())) >= 3,
                         f"{sorted(p.name[:8] for p in (root / str(pid)).iterdir())}")

                # 4) 영구 삭제 → 폴더 삭제
                folder = root / str(pid)
                step('4. 삭제 전: 프로젝트 폴더가 있음', folder.is_dir())
                res = owner.delete(f'/projects/{pid}/permanent')
                step('4. 영구 삭제 204', res.status_code == 204, f'{res.status_code} {j(res) if res.status_code != 204 else ""}')
                step('4. 프로젝트 폴더가 지워짐(SB-294)', not folder.exists(), f'남은 항목 {list(folder.rglob("*")) if folder.exists() else "없음"}')
                res = owner.get(exec_url)
                step('4. 지운 뒤 주소는 404', res.status_code == 404, f'{res.status_code}')

                # 5) 원페이지 — 두 경로가 같은 onepage.svg
                pid2 = drive_to_artifact_review('원페이지')
                art2 = artifact_of(pid2)
                one_url = art2.get('infographic_path')
                step('5. 화면 8: 원페이지 산출물', art2.get('category') == 'onepage', f"category={art2.get('category')}")
                step('5. 인포그래픽 경로가 onepage.svg 주소이고 실행 경로는 없음',
                     bool(url_pattern(pid2, 'onepage.svg').match(one_url or '')) and art2.get('executable_path') is None,
                     f"인포그래픽={one_url} 실행={art2.get('executable_path')}")
                step('5. 저장된 파일은 onepage.svg 하나', sorted(p.name for p in root.glob(f'{pid2}/*/*')) == ['onepage.svg'],
                     str(sorted(str(p.relative_to(root)) for p in root.glob(f'{pid2}/*/*'))))
                one = owner.get(one_url)
                step('5. onepage.svg 내려받기 — 샘플과 바이트가 같음',
                     one.status_code == 200 and one.content == samples['onepage.svg'] and one.headers.get('content-type') == 'image/svg+xml',
                     f"{one.status_code} {len(one.content)}바이트(샘플 {len(samples['onepage.svg'])})")

                # 6) 탈퇴 + 고아 청소
                orphan = root / '987654' / ('c' * 32)
                orphan.mkdir(parents=True)
                (orphan / 'index.html').write_text('<html/>', encoding='utf-8')
                keep_other_name = root / 'notes'
                keep_other_name.mkdir()
                old = time.time() - 7200
                for p in (root / '987654', orphan, orphan / 'index.html'):
                    os.utime(p, (old, old))
                folder2 = root / str(pid2)
                res = owner.delete('/auth/me')
                step('6. 탈퇴 204', res.status_code == 204, f'{res.status_code} {j(res) if res.status_code != 204 else ""}')
                step('6. 탈퇴한 계정의 프로젝트 폴더가 지워짐(SB-294)', not folder2.exists())
                with SessionLocal() as db:
                    live = {pid_ for (pid_,) in db.query(Project.project_id)}
                swept = artifact_store.sweep_orphans(live)
                step('6. 고아 청소: 행이 없는 숫자 폴더만 지움', swept == [987654] and not (root / '987654').exists()
                     and keep_other_name.is_dir(), f'지운 번호={swept}, notes 폴더 남음={keep_other_name.is_dir()}')
                left = sorted(p.name for p in root.iterdir())
                step('6. 마지막에 저장 폴더에는 우리 것이 남지 않음', left == ['notes'], f'{left}')
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
    sys.exit(main())
