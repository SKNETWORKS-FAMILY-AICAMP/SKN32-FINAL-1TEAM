"""사업계획서 .docx → PDF 변환 (LibreOffice headless).

양식을 PDF로 다시 그리지 않고 plan_document_export.render_plan_docx가 만든 docx를
그대로 변환한다 — 이게 이 방식을 고른 이유다. reportlab 등으로 PDF를 따로 그리면
공식 양식(별첨1) 레이아웃 코드가 두 벌이 되고, 한쪽만 고치는 순간 화면 미리보기와
내려받는 파일이 어긋난다(프론트 HTML 미리보기에서 이미 겪은 문제).

실행 파일은 SOFFICE_BIN 환경변수로 지정하고, 없으면 PATH와 OS별 기본 설치 경로를
차례로 찾는다.

서버(리눅스) 배포 시 주의: LibreOffice와 **한글 폰트**가 둘 다 있어야 한다.
폰트가 없으면 변환 자체는 성공하는데 PDF의 한글이 전부 네모(tofu)로 나온다
— docx가 '맑은 고딕'을 쓰므로(plan_document_export.py) fonts-nanum 등 대체 폰트가
필요하다.
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

# 윈도우 개발 환경에서는 PATH에 안 잡히는 게 보통이라 기본 설치 경로도 같이 본다.
_DEFAULT_SOFFICE_PATHS = (
    r'C:\Program Files\LibreOffice\program\soffice.exe',
    r'C:\Program Files (x86)\LibreOffice\program\soffice.exe',
    '/usr/bin/soffice',
    '/usr/bin/libreoffice',
    '/usr/lib/libreoffice/program/soffice',
)

# 변환이 오래 걸릴 일은 없지만, 프로필이 깨져 대화상자를 띄우려 하면 영영 안 끝나므로 상한을 둔다.
_CONVERT_TIMEOUT_SECONDS = 120


class PdfConversionError(RuntimeError):
    """LibreOffice를 못 찾았거나 변환에 실패했을 때. 라우터가 503으로 바꿔 내보낸다."""


def find_soffice() -> str | None:
    """LibreOffice 실행 파일 경로. 못 찾으면 None."""
    configured = os.environ.get('SOFFICE_BIN')
    if configured:
        # 지정했는데 없으면 조용히 다른 걸 쓰지 않는다 — 설정이 틀렸다는 걸 드러내는 편이 낫다.
        return configured if Path(configured).exists() else None
    found = shutil.which('soffice') or shutil.which('libreoffice')
    if found:
        return found
    for candidate in _DEFAULT_SOFFICE_PATHS:
        if Path(candidate).exists():
            return candidate
    return None


def docx_to_pdf(docx_bytes: bytes) -> bytes:
    """docx 바이트를 PDF 바이트로. 실패하면 PdfConversionError."""
    soffice = find_soffice()
    if soffice is None:
        raise PdfConversionError(
            'LibreOffice를 찾을 수 없습니다. 설치 후 SOFFICE_BIN 환경변수로 경로를 지정하세요.'
        )

    with tempfile.TemporaryDirectory(prefix='sbrain-pdf-') as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / 'plan.docx'
        src.write_bytes(docx_bytes)
        # 호출마다 별도 프로필을 쓴다 — 기본 프로필을 공유하면 동시 요청 시
        # "another instance is running"으로 두 번째 변환이 실패한다.
        profile = tmp_path / 'lo-profile'
        try:
            result = subprocess.run(
                [
                    soffice, '--headless', '--norestore',
                    f'-env:UserInstallation={profile.as_uri()}',
                    '--convert-to', 'pdf', '--outdir', str(tmp_path), str(src),
                ],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=_CONVERT_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            raise PdfConversionError(f"LibreOffice 실행에 실패했습니다('{soffice}')") from exc
        except subprocess.TimeoutExpired as exc:
            raise PdfConversionError('PDF 변환이 시간 내에 끝나지 않았습니다.') from exc

        out = tmp_path / 'plan.pdf'
        # soffice는 변환에 실패해도 종료 코드 0을 주는 경우가 있어 결과 파일 존재로 판정한다.
        if not out.exists():
            detail = (result.stderr or result.stdout or '').strip()
            raise PdfConversionError(f'PDF 변환에 실패했습니다. {detail}'.strip())
        return out.read_bytes()
