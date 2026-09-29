# Chroma 실제 벡터 정합성 검사 리뷰

2026-09-21 · Codex · 구현 변경 없이 코드·저장 보고서·가상 반례·현재 로컬 파일 검토

대상:

- `eval/chroma_integrity.py`
- `eval/search_comparison.py`
- `tests/test_chroma_integrity.py`
- `reports/chroma_integrity_20260921T031931Z/`
- [Chroma 검증 작업 지시서](CHROMA_INTEGRITY_TASK_20260918.md)

## 판정

**실데이터 불일치 1건의 발견은 타당하지만, 검사 도구는 수정 후 재검토가 필요하다.**

저장 보고서의 핵심 결과인 `kstartup:179193`의 NPZ↔Chroma 벡터 불일치는 현재 파일에서도 독립적으로
재현됐다. 최대 원소 차이 `0.0193024464`, 코사인 `0.9866377`, 나머지 2,327건의 분류도
바이트 일치 1,775건·재정규화 일치 552건으로 보고서와 같았다. 검사 당시 DB↔NPZ와 메타데이터가
통과했다는 저장 근거도 일관된다.

그러나 아래 세 경로는 지시서의 거짓 통과 방지 및 검색 전 중단 조건을 충족하지 못한다.

## 수정 필요

### [P1] NPZ의 NaN/Inf·잘못된 차원을 검사하지 않아 거짓 통과하거나 예외로 끝남

- 위치: `eval/chroma_integrity.py:132-170`
- `compare_vectors()`는 Chroma 벡터만 차원·유한값 검사하고 NPZ 벡터는 바로 뺄셈에 사용한다.
- NPZ 벡터에 `NaN`이 있고 Chroma 벡터가 정상인 반례를 실행하면 `diff=NaN`이 된다.
  `NaN > 1e-6`이 거짓이므로 최종 상태가 **`통과`**가 되고 `within_tolerance_other=1`로 기록된다.
- NPZ가 2차원, Chroma가 기대 차원 4인 반례는 상태를 반환하지 못하고 broadcasting `ValueError`를 낸다.
  `check()`에서는 넓은 예외 처리로 Chroma 전체 조회 실패처럼 보일 수 있고, `compare_vectors()` 단위 호출은 그대로 중단된다.
- 이는 지시서의 “벡터 누락·차원 불일치·NaN/Inf를 정상 일치로 처리하지 않는다” 조건을 직접 위반한다.

수정 기준:

1. NPZ와 Chroma 양쪽 벡터를 각각 1차원·기대 차원·유한값으로 검증한 뒤에만 비교한다.
2. NPZ 이상과 Chroma 이상을 출처별로 보고하고 상태를 `불일치` 또는 정의한 `확인 실패`로 반환한다.
3. NPZ의 NaN, Inf, 잘못된 차원, ID/벡터/입력해시 길이 불일치 회귀 테스트를 추가한다.
4. NPZ 파일 누락·키 누락·파싱 실패도 traceback만 남기지 말고 `확인 실패` 보고서를 생성한다.

### [P2] DB↔NPZ가 불일치해도 `chroma_content_verified=True`가 될 수 있음

- 위치: `eval/chroma_integrity.py:403-407`
- 현재 플래그는 NPZ↔Chroma와 메타데이터 통과, 검사 중 변경 없음만 확인한다.
  `db_npz` 상태는 포함하지 않는다.
- 가상 DB 입력 해시 한 건만 `OLD`로 바꾸고 NPZ↔Chroma·메타데이터를 정상으로 두면 다음 결과가 재현된다.

```text
전체 status = 불일치
db_npz = 불일치
npz_chroma = 통과
meta = 통과
chroma_content_verified = True
```

`search_comparison.integrity_failures()`가 별도로 DB↔NPZ 불일치를 잡으므로 현재 비교 실행이 그대로 진행되지는
않는다. 하지만 보고서의 대표 플래그가 현재 DB 내용과 이어지지 않은 Chroma를 검증 완료로 표시한다.
지시서는 DB→NPZ→Chroma 전체 검사가 끝난 경우에만 이 값을 true로 요구한다.

수정 기준:

- `db_npz`, `npz_chroma`, `meta`, 스냅샷이 모두 통과한 경우에만 `chroma_content_verified=True`로 둔다.
- DB stale/missing/extra 각각에서 플래그가 false인 회귀 테스트를 추가한다.

### [P2] 정상 비교는 정합성 검사 전에 `app.boot()`와 모델 워밍업을 실행함

- 위치: `eval/search_comparison.py:504-517`, 연결되는 `search/app.py:108-137`.
- `search_comparison.main()`은 `app.boot()` 뒤에 `data_check()`와 `integrity_failures()`를 호출한다.
- `app.boot()`는 원본 Chroma를 열고, DB·BM25를 적재한 뒤 `_encode('워밍업')`으로 모델 추론까지 수행한다.
- 따라서 현재처럼 Chroma 불일치가 있는 경우에도 원본 Chroma 열기와 모델 워밍업이 먼저 일어난 다음 비교가 중단된다.
  실제 검색 40건은 실행하지 않지만, 지시서의 “기존 비교 경로는 검색·워밍업 전에 중단” 조건은 충족하지 못한다.
- `--check-only` 경로는 `app.boot()`를 부르지 않아 정상이다. 문제는 일반 비교 진입점이다.

수정 기준:

1. 일반 비교도 읽기 전용 Chroma 사본 검사로 preflight를 먼저 수행한다.
2. preflight가 통과한 뒤에만 `app.boot()`와 워밍업을 실행한다.
3. 불일치 fixture에서 호출 순서를 기록해 `app.boot`, `_encode`, `app.match`가 모두 호출되지 않는 테스트를 추가한다.
4. 통과 후 `app.boot()`로 만든 DB·BM25·행 ID/내용 검사는 계속 수행해 실행 직전 상태를 확인한다.

## 낮은 우선순위

- `eval/chroma_integrity.py:512`의 `io.open(...).write(...)`는 파일을 명시적으로 닫지 않아 전체 테스트에서
  `ResourceWarning`이 발생한다. `with io.open(...) as f:`로 닫는 것이 좋다.
- 보고서 `code_sha256`에는 검사 도구와 데이터 계약 코드는 있지만 통합 중단 로직을 가진
  `eval/search_comparison.py`는 없다. 일반 비교 재현성을 위해 이 파일 해시도 포함하는 편이 낫다.

## 확인한 정상 동작

- Chroma 원본을 임시 폴더에 복사해 사본을 여는 검사 전용 경로는 적절하다.
- ID 순서와 무관하게 대응하며, 중복·추가·누락·Chroma 벡터 이상·메타데이터 누락을 실패로 처리한다.
- 코사인 유사도만으로 통과시키지 않고 원소별 절대 오차를 사용한다.
- `atol=1e-6`, `rtol=0`을 결과 확인 전에 정했고, 재정규화 차이 최대 `1.49e-8`과 실제 불일치
  `0.0193` 사이에 충분한 간격이 있다.
- 검사 전후 NPZ·Chroma 원본 폴더·DB 입력 집합 변경 감지와 과거 실행에 소급 적용하지 않는 한계 표시가 있다.
- 불일치 상태에서 자동 복구하거나 색인을 재생성하지 않았다.

## 검증 기록

- 신규 `tests.test_chroma_integrity`: **27개 통과**
- 전체 테스트: **273개 통과, 13개 건너뜀**
- 위 P1 가상 반례: NPZ NaN이 `통과`, NPZ 잘못된 차원이 `ValueError`로 재현됨
- 위 P2 가상 반례: `db_npz=불일치`인데 `chroma_content_verified=True` 재현됨
- 저장 보고서의 코드 해시는 현재 검사 코드·임베딩 계약·벡터 저장소·corpus 코드와 일치함
- 현재 NPZ↔Chroma 파일 재검사에서도 `kstartup:179193` 한 건 및 나머지 분류가 저장 보고서와 일치함
- 이번 재검토 시점의 DB 재조회는 `OperationalError`로 실패해 DB↔NPZ 부분을 새 시점에 독립 재확인하지 못했다.
  저장 보고서의 검사 시점에는 2,328건이 통과한 기록이 있다.

## 다음 작업 기준

`vecstore.sync(['kstartup:179193'])` 한 건 재동기화 방향 자체는 현재 불일치에 맞는 최소 수정이다.
하지만 지금 바로 실행하지 말고 다음 순서를 권고한다.

1. 위 P1·P2 세 건과 회귀 테스트를 먼저 수정한다.
2. DB 연결이 정상일 때 `--check-only`를 다시 실행해 DB↔NPZ가 현재도 통과하는지 확인한다.
3. 그 결과가 `kstartup:179193` 한 건만 불일치일 때 사용자 승인 범위로 한 건만 재동기화한다.
4. 다시 `--check-only`를 실행해 세 부분 모두 통과하고 `chroma_content_verified=True`인지 확인한다.
5. 기존 `054314Z` 결과를 소급해 검증 완료로 바꾸지 않는다. 필요하면 통과한 새 시점에 비교를 새 폴더로 실행한다.

구현·테스트·DB·NPZ·Chroma·기존 보고서는 수정하지 않았으며 이 리뷰 문서만 추가했다.
Git 스테이징·커밋·push는 하지 않았다.

---

## 후속 재검토 — 1차 리뷰 반영 결과 (2026-09-21)

### 판정

앞서 지적한 P1·P2·P2 세 건과 낮은 우선순위 두 건은 해결됐다. 다만 일반 비교가 사전 검사 결과를
재사용하는 조건에 새로운 P2 한 건이 남아 있어 **검사 도구 전체 승인은 보류**한다.

최신 실제 검사 `reports/chroma_integrity_20260921T034104Z/`의 결과는 신뢰할 수 있다.
검사 시점 DB↔NPZ 2,328건과 메타데이터는 통과했고, NPZ↔Chroma는 여전히
`kstartup:179193` 한 건만 불일치한다. NPZ 이상은 0건이며 검사 중 변경도 없었다.

### 이전 지적 해결 확인

1. **NPZ 손상 벡터 검사 해결**
   - NPZ와 Chroma 양쪽을 동일하게 1차원·기대 차원·유한값 검사한다.
   - NPZ NaN·Inf·차원 오류가 모두 `불일치`와 `npz_broken` 사유로 반환된다.
   - NPZ 파일·키·배열 길이 문제는 traceback 대신 `확인 실패` 보고서를 생성한다.
2. **대표 검증 플래그 해결**
   - `db_npz`, `npz_chroma`, `meta`, 전체 상태와 검사 중 변경을 모두 확인한 경우만
     `chroma_content_verified=True`가 된다.
   - DB 해시 불일치 반례가 `verified=False`로 바뀐 것을 재현했다.
3. **검색 전 중단 순서 해결**
   - 일반 비교도 `preflight_check()`를 `app.boot()`보다 먼저 실행한다.
   - 현재 실제 일반 비교를 재실행한 결과 종료코드 2로 부팅 전에 멈췄고,
     `chroma.sqlite3` 수정 시각은 실행 전후 동일했다.
4. `summary.md` 파일 닫기와 `eval/search_comparison.py` 코드 해시 기록도 반영됐다.

### [P2] 사전 검사 후 NPZ·Chroma가 바뀌어도 이전 통과 결과를 재사용함

- 위치: `eval/search_comparison.py:195-212`.
- `data_check(preflight)`는 사전 검사의 `corpus_sha256`과 부팅 후 DB corpus 해시만 비교한다.
  둘이 같으면 `content = preflight`로 두고 NPZ↔Chroma 실제 벡터 검사를 다시 하지 않는다.
- 사전 검사 결과에는 NPZ 파일 sha256과 Chroma 폴더 파일 지문이 이미 있지만, 재사용하기 전에
  현재 파일 지문과 비교하지 않는다.
- 따라서 사전 검사 통과 후 `app.boot()` 또는 동시 배치가 NPZ/Chroma 내용을 변경하되 DB 내용은
  그대로인 경우, 부팅 후 검색은 변경 전 통과 판정을 사용한다. ID 집합이 그대로이고 벡터 값만 바뀌면
  뒤의 `db_equals_chroma` 검사도 이를 찾지 못한다.

이는 현재 `179193` 불일치 보고서의 오류가 아니다. 현재 preflight는 애초에 불일치라 부팅 전에 멈춘다.
문제는 향후 색인을 고쳐 preflight가 통과한 뒤 실제 비교를 실행할 때 생길 수 있는 시점 간격이다.

수정 기준:

1. preflight의 `snapshot.after.npz_sha256`·`chroma_files`를 부팅 후 현재 지문과 비교한다.
2. 하나라도 달라졌으면 preflight를 재사용하지 말고 현재 상태로 다시 검사하거나 안전하게 중단한다.
3. DB corpus 해시 비교는 그대로 유지한다.
4. 사전 검사 통과 뒤 NPZ 값만 변경, Chroma 값만 변경, ID는 같고 벡터만 변경한 회귀 테스트를 추가한다.
5. 실제 검색 사례를 실행하기 직전 사용한 데이터 지문을 결과 manifest에 남긴다.

### 재검증

- Chroma 검사 테스트: **40개 통과**
- 전체 테스트: **286개 통과, 13개 건너뜀**
- 실제 일반 비교: 사전 검사에서 종료코드 2, `app.boot()` 미실행, Chroma 원본 수정 시각 불변
- 최신 저장 검사: DB↔NPZ 통과, 메타 통과, NPZ 이상 0, `kstartup:179193` 불일치 1건
- Codex 재실행 시 DB 연결은 `OperationalError`였지만 NPZ↔Chroma 한 건 불일치와 검색 전 중단은 다시 확인했다.
  최신 Claude 저장 검사에서는 같은 코드로 DB 접속이 정상 완료됐다.

### 다음 단계

위 P2를 먼저 고친 뒤 다시 재검토한다. `kstartup:179193` 한 건 재동기화는 기술적으로 최소 수정 방향이
맞지만 Chroma 쓰기이므로 사용자 승인 전에는 실행하지 않는다. 재동기화 후에는 새 `--check-only` 결과에서
세 부분 모두 통과하고 `chroma_content_verified=True`인지 확인해야 한다.

이번 후속 재검토에서도 구현·테스트·DB·NPZ·Chroma·기존 보고서는 수정하지 않았고 이 문서만 갱신했다.
Git 스테이징·커밋·push는 하지 않았다.

---

## 후속 재검토 — 사전 검사 재사용 조건 보완 (2026-09-21)

### 판정

**앞선 후속 리뷰의 P2는 해결됐으며 Chroma 정합성 검사 도구를 승인한다.**

`eval/search_comparison.py`는 이제 사전 검사가 통과한 것만으로 결과를 재사용하지 않는다.
사전 검사 종료 시점의 DB corpus 해시·NPZ 파일 sha256·Chroma 원본 폴더 전체 지문이
`app.boot()` 뒤의 현재 값과 모두 같은 경우에만 재사용한다. 하나라도 다르면
`chroma_integrity.check()`로 현재 DB·NPZ·Chroma를 다시 검사하므로, ID는 같고 벡터 값만 바뀐 경우에도
옛 통과 판정으로 검색을 계속할 수 없다.

검색 사례 실행에 사용한 식별 정보도 최종 manifest의
`data.chroma_content.data_fingerprint`에 DB corpus·NPZ 파일·Chroma 폴더·NPZ/Chroma 벡터 집합 해시로
남는다. 재사용 여부와 재검사 이유는 같은 위치의 `preflight_reused`, `recheck_reason`으로 확인할 수 있다.

### 확인 내용

- `preflight_reuse_problem()`은 통과하지 않은 사전 검사, DB 변경, NPZ 변경, Chroma 변경,
  종료 시점 지문 누락을 모두 재사용 불가로 판정한다.
- `data_check()`는 재사용 불가 사유가 있으면 현재 상태로 전체 검사를 다시 실행하고,
  그 결과의 `chroma_content_verified`를 기존 `integrity_failures()`에 전달한다.
- 실제 `data_check()`의 결과 객체가 그대로 manifest의 `data`에 들어가므로 데이터 지문이 저장 경로에서
  빠지지 않는다.
- 회귀 테스트는 같은 ID를 유지한 채 NPZ 벡터 값만 바꾼 경우와 Chroma 파일만 바꾼 경우를 포함한다.

### 독립 재검증

- `tests/test_chroma_integrity.py`: **46개 통과**
- 전체 테스트: **292개 통과, 13개 건너뜀**
- 실제 일반 비교 재실행: 종료코드 **2**, 사전 검사 단계에서 중단
- Codex 실행 환경에서는 DB 접속이 `OperationalError`여서 DB↔NPZ를 새 시점에 재확인하지 못했다.
  동시에 NPZ↔Chroma의 기존 불일치 1건은 다시 검출됐고, 원본 `chroma.sqlite3` 수정 시각은 실행 전후
  동일해 `app.boot()`·검색이 실행되지 않은 것을 확인했다.
- 최신 저장 검사 `reports/chroma_integrity_20260921T034104Z/`에는 DB 접속이 정상인 시점의
  DB↔NPZ 2,328건 통과와 `kstartup:179193` 한 건의 NPZ↔Chroma 불일치가 기록돼 있다.

### 비차단 관찰

- 전체 테스트에서 기존 `eval/search_comparison.py`의 HTML/`INVALID.md` 쓰기와 테스트의 파일 읽기에서
  `ResourceWarning`이 출력됐다. 이번 재사용 조건이나 판정 결과에는 영향이 없지만 별도 정리할 수 있다.
- 사전 검사 뒤 NPZ 파일이 삭제되는 매우 좁은 경쟁 상황에서는 현재 지문 계산이 `FileNotFoundError`로
  종료될 수 있다. 검색 전 비정상 종료되어 거짓 통과하지는 않으므로 승인 차단 사유는 아니지만,
  사람이 읽는 중단 사유로 바꾸면 진단성이 더 좋아진다.

### 남은 실제 데이터 작업

도구 수정은 승인됐지만 **현재 데이터 자체는 아직 통과 상태가 아니다.**
`kstartup:179193` 한 건 재동기화는 Chroma 쓰기이므로 사용자의 명시적 승인 전에는 실행하지 않는다.
승인 후에는 해당 한 건만 동기화하고 새 `--check-only` 보고서에서 DB↔NPZ·NPZ↔Chroma·메타데이터가
모두 통과하며 `chroma_content_verified=True`인지 확인해야 한다.

이번 재검토에서는 구현·테스트·DB·NPZ·Chroma·기존 보고서를 수정하지 않았고 이 리뷰 문서만 갱신했다.
Git 스테이징·커밋·push는 하지 않았다.
