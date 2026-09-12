"""Tests for all Pydantic schemas — validation and constraints."""

import pytest
from datetime import datetime
from pydantic import ValidationError

from app.schemas.user import (
    UserRegister,
    UserLogin,
    TokenResponse,
    UserResponse,
    UserUpdate,
)
from app.schemas.admin import (
    AdminUserUpdate,
    AdminUserResponse,
    JobProfileCreate,
    JobProfileUpdate,
    DimensionWeightCreate,
    DimensionWeightUpdate,
    AIConfigCreate,
    AIConfigUpdate,
)
from app.schemas.chat import ChatSessionCreate, ChatRequest
from app.schemas.matching import (
    MatchRunRequest,
    FeedbackCreateRequest,
)
from app.schemas.reports import ReportGenerateRequest
from app.schemas.career import CareerPathRequest, GrowthPlanRequest


class TestUserRegisterSchema:
    def test_valid_user_register(self):
        data = {"username": "testuser", "password": "password123"}
        schema = UserRegister(**data)
        assert schema.username == "testuser"
        assert schema.password == "password123"

    def test_username_too_short(self):
        with pytest.raises(ValidationError):
            UserRegister(username="ab", password="password123")

    def test_username_too_long(self):
        with pytest.raises(ValidationError):
            UserRegister(username="a" * 51, password="password123")

    def test_password_too_short(self):
        with pytest.raises(ValidationError):
            UserRegister(username="testuser", password="12345")

    def test_password_too_long(self):
        with pytest.raises(ValidationError):
            UserRegister(username="testuser", password="a" * 129)

    def test_optional_email(self):
        schema = UserRegister(username="testuser", password="password123", email="test@example.com")
        assert schema.email == "test@example.com"

    def test_optional_phone(self):
        schema = UserRegister(username="testuser", password="password123", phone="13800138000")
        assert schema.phone == "13800138000"


class TestUserLoginSchema:
    def test_valid_login(self):
        schema = UserLogin(username="testuser", password="password123")
        assert schema.username == "testuser"


class TestAdminUserUpdateSchema:
    def test_valid_role_admin(self):
        schema = AdminUserUpdate(role="admin")
        assert schema.role == "admin"

    def test_valid_role_student(self):
        schema = AdminUserUpdate(role="student")
        assert schema.role == "student"

    def test_invalid_role(self):
        with pytest.raises(ValidationError):
            AdminUserUpdate(role="superuser")

    def test_valid_status(self):
        schema = AdminUserUpdate(status=0)
        assert schema.status == 0
        schema = AdminUserUpdate(status=1)
        assert schema.status == 1

    def test_invalid_status(self):
        with pytest.raises(ValidationError):
            AdminUserUpdate(status=2)

    def test_valid_password(self):
        schema = AdminUserUpdate(password="newpass123")
        assert schema.password == "newpass123"

    def test_password_too_short(self):
        with pytest.raises(ValidationError):
            AdminUserUpdate(password="12345")


class TestJobProfileCreateSchema:
    def test_valid_minimal(self):
        schema = JobProfileCreate(title="软件工程师")
        assert schema.title == "软件工程师"

    def test_title_required(self):
        with pytest.raises(ValidationError):
            JobProfileCreate()

    def test_title_too_long(self):
        with pytest.raises(ValidationError):
            JobProfileCreate(title="a" * 201)

    def test_with_all_fields(self):
        schema = JobProfileCreate(
            title="软件工程师",
            industry="互联网",
            level="中级",
            hard_skills={"Python": 4, "Java": 3},
            salary_range="15k-25k",
        )
        assert schema.industry == "互联网"
        assert schema.hard_skills == {"Python": 4, "Java": 3}


class TestJobProfileUpdateSchema:
    def test_empty_update(self):
        schema = JobProfileUpdate()
        assert schema.title is None

    def test_partial_update(self):
        schema = JobProfileUpdate(title="新标题")
        assert schema.title == "新标题"
        assert schema.industry is None


class TestDimensionWeightCreateSchema:
    def test_valid_weight(self):
        schema = DimensionWeightCreate(
            job_category="技术",
            top_dimension="专业能力",
            weight=0.8,
        )
        assert schema.weight == 0.8

    def test_weight_boundary_zero(self):
        schema = DimensionWeightCreate(
            job_category="技术",
            top_dimension="专业能力",
            weight=0.0,
        )
        assert schema.weight == 0.0

    def test_weight_boundary_one(self):
        schema = DimensionWeightCreate(
            job_category="技术",
            top_dimension="专业能力",
            weight=1.0,
        )
        assert schema.weight == 1.0

    def test_weight_out_of_range(self):
        with pytest.raises(ValidationError):
            DimensionWeightCreate(
                job_category="技术",
                top_dimension="专业能力",
                weight=1.5,
            )


class TestAIConfigCreateSchema:
    def test_valid_config(self):
        schema = AIConfigCreate(
            function_key="resume_parsing",
            provider="deepseek",
            model_name="deepseek-chat",
        )
        assert schema.function_key == "resume_parsing"
        assert schema.temperature == 0.7
        assert schema.max_tokens == 4096

    def test_temperature_boundary(self):
        schema = AIConfigCreate(
            function_key="test",
            provider="test",
            model_name="test",
            temperature=0.0,
        )
        assert schema.temperature == 0.0

        schema = AIConfigCreate(
            function_key="test",
            provider="test",
            model_name="test",
            temperature=2.0,
        )
        assert schema.temperature == 2.0

    def test_temperature_out_of_range(self):
        with pytest.raises(ValidationError):
            AIConfigCreate(
                function_key="test",
                provider="test",
                model_name="test",
                temperature=3.0,
            )

    def test_max_tokens_out_of_range(self):
        with pytest.raises(ValidationError):
            AIConfigCreate(
                function_key="test",
                provider="test",
                model_name="test",
                max_tokens=0,
            )


class TestAIConfigUpdateSchema:
    def test_empty_update(self):
        schema = AIConfigUpdate()
        assert schema.provider is None
        assert schema.is_active is None

    def test_partial_update(self):
        schema = AIConfigUpdate(is_active=True)
        assert schema.is_active is True


class TestChatRequestSchema:
    def test_valid_message(self):
        schema = ChatRequest(content="你好")
        assert schema.content == "你好"

    def test_empty_content(self):
        with pytest.raises(ValidationError):
            ChatRequest(content="")

    def test_content_too_long(self):
        with pytest.raises(ValidationError):
            ChatRequest(content="a" * 2001)


class TestMatchRunRequestSchema:
    def test_valid_request(self):
        schema = MatchRunRequest(profile_id=1)
        assert schema.profile_id == 1
        assert schema.top_k == 10
        assert schema.max_distance == 0.5

    def test_top_k_boundary(self):
        schema = MatchRunRequest(profile_id=1, top_k=1)
        assert schema.top_k == 1
        schema = MatchRunRequest(profile_id=1, top_k=50)
        assert schema.top_k == 50

    def test_top_k_out_of_range(self):
        with pytest.raises(ValidationError):
            MatchRunRequest(profile_id=1, top_k=0)
        with pytest.raises(ValidationError):
            MatchRunRequest(profile_id=1, top_k=51)


class TestFeedbackCreateRequestSchema:
    def test_valid_feedback(self):
        schema = FeedbackCreateRequest(match_id=1, feedback_type="like")
        assert schema.feedback_type == "like"

    def test_invalid_feedback_type(self):
        with pytest.raises(ValidationError):
            FeedbackCreateRequest(match_id=1, feedback_type="invalid")

    def test_all_valid_types(self):
        for fb_type in ["like", "dislike", "applied", "saved"]:
            schema = FeedbackCreateRequest(match_id=1, feedback_type=fb_type)
            assert schema.feedback_type == fb_type


class TestCareerPathRequestSchema:
    def test_valid_request(self):
        schema = CareerPathRequest(profile_id=1, target_job_id=2)
        assert schema.profile_id == 1
        assert schema.target_job_id == 2
        assert schema.current_stage == "在校学生"


class TestGrowthPlanRequestSchema:
    def test_valid_request(self):
        schema = GrowthPlanRequest(growth_path_id=1)
        assert schema.growth_path_id == 1
        assert schema.weekly_hours == 10
        assert schema.cycle_weeks == 12

    def test_weekly_hours_boundary(self):
        schema = GrowthPlanRequest(growth_path_id=1, weekly_hours=1)
        assert schema.weekly_hours == 1
        schema = GrowthPlanRequest(growth_path_id=1, weekly_hours=40)
        assert schema.weekly_hours == 40

    def test_weekly_hours_out_of_range(self):
        with pytest.raises(ValidationError):
            GrowthPlanRequest(growth_path_id=1, weekly_hours=0)
        with pytest.raises(ValidationError):
            GrowthPlanRequest(growth_path_id=1, weekly_hours=41)


class TestReportGenerateRequestSchema:
    def test_valid_request(self):
        schema = ReportGenerateRequest(profile_id=1)
        assert schema.profile_id == 1
        assert schema.target_job is None

    def test_with_target_job(self):
        schema = ReportGenerateRequest(profile_id=1, target_job="软件工程师")
        assert schema.target_job == "软件工程师"
