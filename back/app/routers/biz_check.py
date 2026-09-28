"""사업자등록번호 상태 확인 — 국세청 사업자등록정보 상태조회 API(공공데이터포털)를
프론트 대신 서버에서 호출한다. 프론트가 직접 부르면 서비스키가 그대로 노출된다.

업종·개업일·주소는 이 API 응답에 없다(진위확인 API는 "이미 알고 있는 값이 맞는지
대조"하는 용도라 그 값들을 입력으로 받지, 조회해서 알려주지 않는다) — 그런 필드는
그대로 사용자 직접 입력으로 남긴다. 여기서 자동화하는 건 영업상태·과세유형뿐이다.

[2026-09-17 추가, SB-59; 2026-09-18 v2로 슬롯 대응] 조회가 성공(등록된 번호로 확인)하면
그 결과를 요청 바디의 profile_id가 가리키는 마이페이지 정보 슬롯(user_profiles)에
upsert한다 — PUT /profile/{profile_id} 바디로는 이 결과를 못 바꾸게 막아뒀으므로
(app/routers/profile.py), 실제로 값을 채우는 유일한 경로가 여기다. profile_id를 안 보내면
(계정에 어느 슬롯을 채울지 알 수 없으니) 조회 결과만 돌려주고 아무 슬롯에도 저장하지 않는다.
"""
import datetime
import re

import requests
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserProfile
from app.schemas import BizCheckOut, BizCheckRequest
from app.security import get_current_user

import config

router = APIRouter(prefix='/biz-check', tags=['biz-check'])

_STATUS_URL = 'https://api.odcloud.kr/api/nts-businessman/v1/status'
_STATUS_LABEL = {'01': '계속사업자', '02': '휴업자', '03': '폐업자'}


def _apply_biz_check_result(db: Session, user_id: int, profile_id: int, b_no: str, out: BizCheckOut) -> None:
    profile = db.get(UserProfile, profile_id)
    if profile is None or profile.user_id != user_id:
        raise HTTPException(status_code=404, detail='정보 슬롯을 찾을 수 없습니다')
    profile.biz_checked_no = b_no
    profile.biz_status_cd = out.b_stt_cd
    profile.biz_tax_type = out.tax_type
    profile.biz_checked_at = datetime.datetime.utcnow()
    db.commit()


@router.post('', response_model=BizCheckOut)
def check_business_number(
    body: BizCheckRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    b_no = re.sub(r'\D', '', body.b_no)
    if len(b_no) != 10:
        raise HTTPException(status_code=400, detail='사업자등록번호는 숫자 10자리여야 합니다')

    service_key = config.require('NTS_SERVICE_KEY')

    try:
        resp = requests.post(
            _STATUS_URL,
            params={'serviceKey': service_key},
            json={'b_no': [b_no]},
            timeout=5,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail='국세청 API 호출에 실패했습니다') from exc

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f'국세청 API 오류 (HTTP {resp.status_code})')

    result = resp.json()
    if result.get('match_cnt', 0) == 0:
        return BizCheckOut(valid=False, message='등록되지 않은 사업자등록번호입니다')

    item = result['data'][0]
    stt_cd = item.get('b_stt_cd')
    out = BizCheckOut(
        valid=True,
        b_stt_cd=stt_cd,
        label=_STATUS_LABEL.get(stt_cd, item.get('b_stt')),
        tax_type=item.get('tax_type'),
        tax_type_cd=item.get('tax_type_cd'),
    )
    if body.profile_id is not None:
        _apply_biz_check_result(db, current_user.user_id, body.profile_id, b_no, out)
    return out
