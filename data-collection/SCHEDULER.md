# 매일 자동 실행 걸기 — 사용 설명서

공고 수집 배치를 Windows 작업 스케줄러에 등록해 **매일 정해진 시각에 저절로 돌게** 합니다.
한 번 등록해두면 그 뒤로는 아무것도 누르지 않아도 됩니다.

---

## 준비 — 이것부터 되어 있어야 합니다

**1. 가상환경**

```powershell
cd C:\mok_workspace\finak_mok\collector
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**2. `.env` 에 인증키와 DB 정보**

```powershell
Copy-Item .env.example .env
notepad .env
```

`KSTARTUP_KEY`, `BIZINFO_KEY`, `MYSQL_*` 을 채웁니다.

**3. 손으로 한 번 돌려보기**

```powershell
.\.venv\Scripts\python.exe -X utf8 daily_pipeline.py
```

**여기서 성공해야 예약을 겁니다.** 실패하는 걸 예약해두면 매일 조용히 실패합니다.

---

## 등록하기

PowerShell 창을 열고 이 폴더에서 실행합니다.
**`.ps1` 은 더블클릭으로 실행되지 않습니다.** 메모장이 열립니다.

### 먼저 미리보기

```powershell
.\schedule-task.ps1
```

무엇이 등록될지 보여주기만 하고 **아무것도 바꾸지 않습니다.**

```
TaskName           : S-Brain-DailyCollection
DailyAt            : 09:00
Command            : C:\...\collector\run_daily.bat
LogonType          : S4U
PythonReady        : True
AlreadyRegistered  : False
```

`PythonReady` 가 `False` 면 가상환경이 없는 것입니다. 준비 1번으로 돌아가세요.

### 실제로 등록

```powershell
.\schedule-task.ps1 -Mode Install
```

시각을 바꾸려면,

```powershell
.\schedule-task.ps1 -Mode Install -At 08:30
```

관리자 권한을 요구할 수 있습니다. 그때는 **PowerShell 을 「관리자 권한으로 실행」** 해서 다시 하세요.

---

## 잘 되고 있는지 보기

```powershell
.\schedule-task.ps1 -Mode Status
```

```
TaskName       : S-Brain-DailyCollection
State          : Ready
UserId         : playdata2
LogonType      : S4U
LastRunTime    : 2026-09-11 09:00:01
NextRunTime    : 2026-09-12 09:00:00
LastTaskResult : 0
결과: 성공
```

`LastTaskResult` 를 말로 풀어서 같이 보여줍니다.

| 숫자 | 뜻 | 어떻게 하나 |
|---|---|---|
| `0` | 성공 | — |
| `1` | 수집 실패 또는 예외 | `data\run.log` 를 본다 |
| `2` | 부분 실패 — 한 출처만 갱신 안 됨 | 그 출처는 어제 데이터를 쓴다. 다음 날 대개 회복된다 |
| `3` | 이미 실행 중이라 종료 | 정상. 앞 실행이 아직 도는 중이다 |
| `267009` | 지금 실행 중 | 정상 |
| `3221225786` | **외부에서 강제 종료됨** | 아래 「자주 겪는 문제」 참조 |

---

## 지금 한 번 돌려보기

예약 시각을 기다리지 않고 바로 실행합니다.

```powershell
.\schedule-task.ps1 -Mode Run
```

진행 상황은 로그에서 봅니다.

```powershell
Get-Content data\run.log -Tail 20 -Wait
```

`-Wait` 를 붙이면 새 줄이 나올 때마다 화면에 이어 나옵니다. `Ctrl+C` 로 빠져나옵니다.

---

## 해제하기

```powershell
.\schedule-task.ps1 -Mode Uninstall
```

---

## 자주 겪는 문제

### 「이 시스템에서 스크립트를 실행할 수 없습니다」

다른 PC 에서 흔히 납니다. 그 실행에만 정책을 풀어서 돌립니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\schedule-task.ps1 -Mode Install
```

시스템 설정을 바꾸지 않습니다.

### `LastTaskResult` 가 `3221225786` (0xC000013A)

**밖에서 프로세스가 강제로 종료됐다는 뜻**입니다. 실제로 겪은 적이 있습니다 —
09:00에 시작해 3초 만에 죽고, 그날 수집이 통째로 안 됐는데 아무도 몰랐습니다.

원인은 대개 `LogonType` 입니다.

```powershell
.\schedule-task.ps1 -Mode Status      # LogonType 을 확인
```

`Interactive` 로 되어 있으면 **사용자 세션 안에서 도는 것**이라 로그오프·절전·잠금 해제 때
같이 죽습니다. `S4U` 로 바꿉니다.

```powershell
.\schedule-task.ps1 -Mode Uninstall
.\schedule-task.ps1 -Mode Install     # 기본이 S4U 다
```

원인을 확실히 보려면 작업 스케줄러 기록을 켜둡니다 (관리자 권한).

```powershell
wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true
```

기본으로 꺼져 있어서, 켜두지 않으면 다음에 죽어도 이유를 알 수 없습니다.

### 로그에 `start` 는 있는데 `exit=` 가 없다

```
[2026-09-10  9:00:01.90] start
                                  ← exit= 줄이 없다
```

**배치 파일까지 같이 죽었다는 뜻**입니다. 위 `0xC000013A` 와 같은 상황입니다.
정상 종료라면 반드시 `exit=` 줄이 남습니다.

### 「이미 등록돼 있습니다」

같은 이름이 이미 있습니다. 상태를 확인하고, 다시 등록하려면 해제 후 진행합니다.

```powershell
.\schedule-task.ps1 -Mode Status
.\schedule-task.ps1 -Mode Uninstall
.\schedule-task.ps1 -Mode Install
```

### PC 가 꺼져 있어서 09:00을 놓쳤다

**켜지면 자동으로 돕니다.** `StartWhenAvailable` 이 켜져 있어서 놓친 실행을 처리합니다.
다만 며칠씩 꺼져 있으면 그동안은 수집이 안 됩니다.

---

## 알아둘 것

### 이 배치는 한 곳에서만 돌립니다

여러 명이 각자 돌리면 **같은 데이터를 중복으로 받을 뿐** 얻는 게 없습니다.
같은 DB 에 쓰기 때문에 API 호출과 첨부 다운로드만 몇 배로 늘어납니다.

데이터가 깨지지는 않습니다 — `GET_LOCK` 으로 동시 쓰기를 막고,
수집 시각을 비교해 오래된 데이터가 최신을 덮어쓰지 않게 합니다.
그래도 **담당자 한 명만 예약을 걸어두는 것**이 맞습니다.

조회만 하실 분은 읽기 전용 DB 계정을 쓰세요.

### 실행 시각을 바꾸려면

한 번 해제하고 다시 등록합니다.

```powershell
.\schedule-task.ps1 -Mode Uninstall
.\schedule-task.ps1 -Mode Install -At 08:30
```

### GUI 로도 볼 수 있습니다

`Win + R` → `taskschd.msc` → 작업 스케줄러 라이브러리에서
`S-Brain-DailyCollection` 을 찾으면 됩니다. 여기서 켜고 끄고 실행할 수 있습니다.

---

## 한 장 요약

```powershell
# 준비
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env        # 값을 채운다
.\.venv\Scripts\python.exe -X utf8 daily_pipeline.py    # 손으로 한 번 성공시킨다

# 등록
.\schedule-task.ps1                # 미리보기
.\schedule-task.ps1 -Mode Install  # 매일 09:00

# 확인
.\schedule-task.ps1 -Mode Status
Get-Content data\run.log -Tail 20
```
