"""사업자등록번호 상태 확인 — 국세청 사업자등록정보 상태조회 API(공공데이터포털)를
프론트 대신 서버에서 호출한다. 프론트가 직접 부르면 서비스키가 그대로 노출된다.

업종·개업일·주소는 이 API 응답에 없다(진위확인 API는 "이미 알고 있는 값이 맞는지
대조"하는 용도라 그 값들을 입력으로 받지, 조회해서 알려주지 않는다) — 그런 필드는
그대로 사용자 직접 입력으로 남긴다. 여기서 자동화하는 건 영업상태·과세유형뿐이다.
"""
import re

import requests
from fastapi import APIRouter, Depends, HTTPException

from app.models import User
from app.schemas import BizCheckOut, BizCheckRequest
from app.security import get_current_user

import config

router = APIRouter(prefix='/biz-check', tags=['biz-check'])

_STATUS_URL = 'https://api.odcloud.kr/api/nts-businessman/v1/status'
_STATUS_LABEL = {'01': '계속사업자', '02': '휴업자', '03': '폐업자'}


@router.post('', response_model=BizCheckOut)
def check_business_number(
    body: BizCheckRequest,
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
    return BizCheckOut(
        valid=True,
        b_stt_cd=stt_cd,
        label=_STATUS_LABEL.get(stt_cd, item.get('b_stt')),
        tax_type=item.get('tax_type'),
        tax_type_cd=item.get('tax_type_cd'),
    )
