"""마이페이지 프로필 저장/조회 — SB-59 v2. 계정당 최대 3개 정보 슬롯을 둘 수 있다
(front/src/store/useMyPageStore.js MAX_PROFILES와 동일). v1(계정당 1행, GET·PUT /profile/me)은
정재희님의 새 프론트(다중 슬롯) 커밋을 받은 뒤 DROP+CREATE로 완전히 대체했다 — 프론트가
아직 /profile/me를 호출한 적이 없었고(순수 localStorage), v1 스키마가 새 프론트 모양과
근본적으로 안 맞아 나란히 유지할 실익이 없었다.

faqs.py와 같은 구조(로그인 필수, Depends(get_current_user)). 요청·응답 모양은 프론트
스토어의 profile 객체와 1:1로 맞춰서 프론트에서 변환 코드가 필요 없게 한다.
"""
import copy
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserProfile
from app.routers.biz_check import _STATUS_LABEL
from app.schemas import (
    MAX_PROFILES,
    PROFILE_DEFAULT_CAPABILITY,
    ProfileOut,
    ProfileSaveRequest,
)
from app.security import get_current_user

router = APIRouter(prefix='/profile', tags=['profile'])


def _format_biz_no(digits: str | None) -> str | None:
    """000-00-00000 하이픈 형식으로 — 프론트 입력칸(bizNo, 하이픈 있는 형식)과 그대로
    비교할 수 있어야 한다는 요구사항 때문(bizStatus.checkedNo)."""
    if not digits or len(digits) != 10:
        return digits
    return f'{digits[0:3]}-{digits[3:5]}-{digits[5:10]}'


def _biz_status_out(profile: UserProfile) -> dict | None:
    if not profile.biz_checked_no:
        return None
    return {
        'valid': True,
        'b_stt_cd': profile.biz_status_cd,
        'label': _STATUS_LABEL.get(profile.biz_status_cd, profile.biz_status_cd),
        'tax_type': profile.biz_tax_type,
        'checkedNo': _format_biz_no(profile.biz_checked_no),
    }


def _profile_out(profile: UserProfile) -> ProfileOut:
    return ProfileOut(
        profile_id=profile.profile_id,
        name=profile.name,
        basic=profile.basic_json,
        capability=profile.capability_json,
        biz_status=_biz_status_out(profile),
    )


def _get_owned_profile(db: Session, user_id: int, profile_id: int) -> UserProfile:
    profile = db.get(UserProfile, profile_id)
    if profile is None or profile.user_id != user_id:
        raise HTTPException(status_code=404, detail='정보 슬롯을 찾을 수 없습니다')
    return profile


# [2026-09-18, 정재희님 인계서 "필수 입력 항목" 표] 신청자 유형은 항상 필수, 대표자
# 정보(이름·생년월일·성별)·지역(시/도)·주업종도 항상 필수, 대표자 이력 1건 이상도 항상
# 필수 — individual/corp면 사업자번호(작성 여부만, 국세청 조회 성공까지는 요구 안 함)까지.
_APPLICANT_TYPES_REQUIRING_BIZ_NO = {'individual', 'corp'}


def profile_satisfies_required_fields(profile: UserProfile) -> bool:
    """[2026-09-22 수정, 프론트 전달사항 9번] front/src/features/mypage/derive.js의
    missingRequiredFields()가 이미 확정한 필수 기준 그대로 서버도 검사하도록 맞췄다 —
    예전엔 서버가 더 느슨해서(capability.skills/팀 구성 완전성/개인·법인의 openedAt을
    안 봄) 충돌은 없었지만 기준이 어긋나 있었다."""
    basic = profile.basic_json or {}
    capability = profile.capability_json or {}
    applicant_type = basic.get('applicantType')
    if not applicant_type:
        return False
    if not (basic.get('ceoName') and basic.get('birthDate') and basic.get('gender')):
        return False
    if not (basic.get('region') or {}).get('sido'):
        return False
    if not (basic.get('industry') or '').strip():
        return False
    if applicant_type in _APPLICANT_TYPES_REQUIRING_BIZ_NO and not (basic.get('bizNo') and basic.get('openedAt')):
        return False
    if not capability.get('careers') or not (capability.get('skills') or '').strip():
        return False
    solo_founder = bool(capability.get('soloFounder'))
    team = capability.get('team') or []
    team_complete = bool(team) and all(
        (row.get('name') or '').strip() and (row.get('role') or '').strip() and (row.get('career') or '').strip()
        for row in team
    )
    if not solo_founder and not team_complete:
        return False
    return True


def compute_has_profile(db: Session, user_id: int) -> bool:
    """/auth/me와 로그인 응답의 UserOut.has_profile이 쓰는 계산 — 컬럼으로 안 만들고
    매 요청 계산한다(user_profiles가 계정당 최대 3행뿐이라 비용이 미미함). 슬롯 하나라도
    필수 입력 항목을 전부 채웠으면 True — App.jsx의 "시작하기" 게이트가 로그아웃/다른
    기기 로그인 후에도 이 값을 기준으로 판단해야 마이페이지 정보가 안 사라진 것처럼
    보인다(기존엔 브라우저 로컬 상태만 보고 판단해서 로그아웃하면 초기화됐었음)."""
    profiles = db.query(UserProfile).filter(UserProfile.user_id == user_id).all()
    return any(profile_satisfies_required_fields(p) for p in profiles)


@router.get('', response_model=list[ProfileOut])
def list_profiles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """저장한 슬롯이 하나도 없으면 빈 배열 — 프론트는 이걸 "아직 onboarded 안 됨"으로
    본다(useMyPageStore.js와 달리 서버는 항상 빈 초기 슬롯을 미리 만들어두지 않는다:
    실제로 저장 버튼을 눌러야만 행이 생긴다)."""
    profiles = (
        db.query(UserProfile)
        .filter(UserProfile.user_id == current_user.user_id)
        .order_by(UserProfile.profile_id)
        .all()
    )
    return [_profile_out(p) for p in profiles]


@router.post('', response_model=ProfileOut, status_code=201)
def create_profile(
    body: ProfileSaveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing_count = db.query(UserProfile).filter(UserProfile.user_id == current_user.user_id).count()
    if existing_count >= MAX_PROFILES:
        # [2026-09-18, 정재희님 인계서] "이미 3개면 409" — 입력값 자체가 잘못된 게 아니라
        # 계정 상태와 충돌하는 요청이라 422(검증 실패)가 아니라 409(Conflict)로 맞춘다.
        raise HTTPException(status_code=409, detail=f'정보 슬롯은 계정당 최대 {MAX_PROFILES}개까지만 만들 수 있습니다')

    profile = UserProfile(
        user_id=current_user.user_id,
        name=body.name or f'정보 {existing_count + 1}',
        basic_json=body.basic.model_dump(by_alias=True),
        capability_json=body.capability or copy.deepcopy(PROFILE_DEFAULT_CAPABILITY),
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return _profile_out(profile)


@router.put('/{profile_id}', response_model=ProfileOut)
def update_profile(
    profile_id: int,
    body: ProfileSaveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = _get_owned_profile(db, current_user.user_id, profile_id)
    basic = body.basic

    biz_no_digits = re.sub(r'\D', '', basic.biz_no)
    biz_no_column = biz_no_digits if len(biz_no_digits) == 10 else None

    # 저장한 bizNo가 (/biz-check로) 조회했던 번호와 달라지면 조회 결과 컬럼을 비운다 —
    # 재조회 전까지는 지금 입력한 번호에 대한 확인 결과가 아니므로.
    if biz_no_column != profile.biz_checked_no:
        profile.biz_checked_no = None
        profile.biz_status_cd = None
        profile.biz_tax_type = None
        profile.biz_checked_at = None

    if body.name:
        profile.name = body.name
    # 화면 원본은 받은 그대로 통째로 저장(프론트 변환 코드 불필요) — basic은 alias(camelCase)
    # 모양으로 되돌려서 저장해야 프론트 스토어 셋과 1:1로 맞는다.
    profile.basic_json = basic.model_dump(by_alias=True)
    profile.capability_json = body.capability

    db.commit()
    db.refresh(profile)
    return _profile_out(profile)


@router.delete('/{profile_id}', status_code=204)
def delete_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = _get_owned_profile(db, current_user.user_id, profile_id)
    db.delete(profile)
    db.commit()
