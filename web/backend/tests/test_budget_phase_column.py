"""project_budget_items.phase 컬럼 (SB-328) — 예비창업 사업비의 1단계 · 2단계 구분. 비어 있으면 NULL(초기창업 · 개인사업자 · 법인)."""
from sqlalchemy import inspect

from app import models


def _project(db):
    user = models.User(email='phase@example.com', name='가', google_sub='sub-phase')
    db.add(user)
    db.flush()
    company = models.Company(user_id=user.user_id, applicant_type='preliminary', ceo_name='가')
    db.add(company)
    db.flush()
    project = models.Project(company_id=company.company_id, description='프로젝트')
    db.add(project)
    db.flush()
    return project


def test_phase_column_is_nullable_varchar_10(db_session):
    columns = inspect(db_session.get_bind()).get_columns('project_budget_items')
    phase = next(c for c in columns if c['name'] == 'phase')
    assert phase['nullable'] is True
    assert phase['type'].length == 10


def test_phase_defaults_to_none_and_keeps_given_value(db_session):
    project = _project(db_session)
    db_session.add_all([
        models.ProjectBudgetItem(project_id=project.project_id, item_order=1, category='외주용역비'),
        models.ProjectBudgetItem(project_id=project.project_id, item_order=2, category='재료비', phase='1단계'),
        models.ProjectBudgetItem(project_id=project.project_id, item_order=3, category='광고선전비', phase='2단계'),
    ])
    db_session.commit()
    rows = db_session.query(models.ProjectBudgetItem).order_by(models.ProjectBudgetItem.item_order).all()
    assert [r.phase for r in rows] == [None, '1단계', '2단계']
