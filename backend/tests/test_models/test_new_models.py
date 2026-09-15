import pytest
from sqlalchemy import inspect

from app.domain.models import ProfileSnapshot, ReportRecord, StudentProfile
from app.domain.models.user import User
from app.domain.models.resume import Resume


def test_new_tables_registered_on_base():
    tables = {t.name for t in User.metadata.tables.values()}
    assert "profile_snapshots" in tables
    assert "report_records" in tables
    assert "student_profiles" in tables
    # 旧表名确认不再被 metadata 注册
    for gone in ("ability_profiles", "career_reports", "job_matches",
                 "user_match_embeddings", "growth_paths", "growth_plans"):
        assert gone not in tables


def test_profile_snapshot_columns():
    cols = {c.name for c in ProfileSnapshot.__table__.columns}
    assert {"user_id", "profile_id", "form_raw_json", "five_layers_json",
            "six_dim_scores_json", "embedding", "serial_no", "description",
            "matched_at"} <= cols
    # embedding 是 pgvector Vector(1024)
    from pgvector.sqlalchemy import Vector
    vec_col = ProfileSnapshot.__table__.columns["embedding"].type
    assert isinstance(vec_col, Vector) and vec_col.dim == 1024
    # matched_at 可空（未匹配时 NULL；决策 #2）
    assert ProfileSnapshot.__table__.columns["matched_at"].nullable


def test_profile_snapshot_matched_at_is_optional():
    import uuid as _uuid
    snap = ProfileSnapshot(
        user_id=1, profile_id=1,
        form_raw_json={"basic": {}}, five_layers_json={},
        six_dim_scores_json={}, embedding=[0.0] * 1024,
        serial_no=_uuid.uuid4(), description="",
    )
    assert snap.matched_at is None


def test_student_profile_is_lean():
    cols = {c.name for c in StudentProfile.__table__.columns}
    assert cols >= {"user_id", "resume_form", "created_at", "updated_at"}
    assert "real_name" not in cols


def test_user_portrait_columns_removed():
    cols = {c.name for c in User.__table__.columns}
    assert "real_name" not in cols and "age" not in cols


def test_resume_profile_id_removed():
    cols = {c.name for c in Resume.__table__.columns}
    assert "profile_id" not in cols