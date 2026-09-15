"""Tests for domain/services/ — chat_service and matching_service."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skip(reason="旧表已删除，新端点待 Task 5/6")

from app.domain.services.chat_service import (
    create_chat_session,
    list_chat_sessions,
    get_chat_session,
    delete_chat_session,
    get_chat_messages,
    save_chat_message,
)
from app.domain.services.matching_service import (
    get_user_vector,
    get_match_history,
    create_feedback,
    get_user_feedbacks,
)
from app.schemas.matching import FeedbackCreateRequest


def asyncio_run(coro):
    """Helper to run async coroutine in sync test."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _mock_execute_result(scalars_all=None, scalar_one=None):
    """Helper to create a mock execute result chain."""
    mock_result = MagicMock()
    if scalars_all is not None:
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = scalars_all
        mock_result.scalars.return_value = mock_scalars
    mock_result.scalar_one_or_none.return_value = scalar_one
    return mock_result


class TestCreateChatSession:
    def test_creates_session_with_default_title(self):
        session = AsyncMock()
        session.flush = AsyncMock()
        result = asyncio_run(create_chat_session(session, user_id=1))
        assert result.user_id == 1
        assert result.title == "新的对话"

    def test_creates_session_with_custom_title(self):
        session = AsyncMock()
        session.flush = AsyncMock()
        result = asyncio_run(create_chat_session(session, user_id=1, title="测试对话"))
        assert result.title == "测试对话"


class TestListChatSessions:
    def test_returns_empty_list_when_no_sessions(self):
        session = AsyncMock()
        session.execute.return_value = _mock_execute_result(scalars_all=[])
        items, total = asyncio_run(list_chat_sessions(session, user_id=1))
        assert items == []
        assert total == 0

    def test_returns_sessions_with_pagination(self):
        session = AsyncMock()
        mock_sessions = [MagicMock(), MagicMock(), MagicMock()]
        session.execute.return_value = _mock_execute_result(scalars_all=mock_sessions)
        items, total = asyncio_run(list_chat_sessions(session, user_id=1, limit=2))
        assert total == 3


class TestGetChatSession:
    def test_returns_session_when_exists(self):
        session = AsyncMock()
        mock_session = MagicMock()
        session.execute.return_value = _mock_execute_result(scalar_one=mock_session)
        result = asyncio_run(get_chat_session(session, session_id=uuid4(), user_id=1))
        assert result == mock_session

    def test_returns_none_when_not_exists(self):
        session = AsyncMock()
        session.execute.return_value = _mock_execute_result(scalar_one=None)
        result = asyncio_run(get_chat_session(session, session_id=uuid4(), user_id=1))
        assert result is None


class TestDeleteChatSession:
    def test_deletes_existing_session(self):
        session = AsyncMock()
        mock_session = MagicMock()
        session.execute.return_value = _mock_execute_result(scalar_one=mock_session)
        result = asyncio_run(delete_chat_session(session, session_id=uuid4(), user_id=1))
        assert result is True

    def test_returns_false_when_session_not_exists(self):
        session = AsyncMock()
        session.execute.return_value = _mock_execute_result(scalar_one=None)
        result = asyncio_run(delete_chat_session(session, session_id=uuid4(), user_id=1))
        assert result is False


class TestGetChatMessages:
    def test_returns_messages_ordered_by_created_at(self):
        session = AsyncMock()
        mock_messages = [MagicMock(), MagicMock()]
        session.execute.return_value = _mock_execute_result(scalars_all=mock_messages)
        result = asyncio_run(get_chat_messages(session, session_id=uuid4()))
        assert len(result) == 2


class TestSaveChatMessage:
    def test_saves_message_with_defaults(self):
        session = AsyncMock()
        session.flush = AsyncMock()
        result = asyncio_run(save_chat_message(
            session, session_id=uuid4(), role="user", content="你好"
        ))
        assert result.role == "user"
        assert result.content == "你好"
        assert result.tokens_used == 0

    def test_saves_message_with_tokens(self):
        session = AsyncMock()
        session.flush = AsyncMock()
        result = asyncio_run(save_chat_message(
            session, session_id=uuid4(), role="assistant", content="回复",
            tokens_used=100, model_used="deepseek-chat"
        ))
        assert result.tokens_used == 100
        assert result.model_used == "deepseek-chat"


class TestGetUserVector:
    def test_returns_vector_when_exists(self):
        session = AsyncMock()
        mock_embedding = MagicMock()
        mock_embedding.embedding = [0.1, 0.2, 0.3]
        session.execute.return_value = _mock_execute_result(scalar_one=mock_embedding)
        result = asyncio_run(get_user_vector(user_id=1, profile_id=1, session=session))
        assert result == [0.1, 0.2, 0.3]

    def test_returns_none_when_not_exists(self):
        session = AsyncMock()
        session.execute.return_value = _mock_execute_result(scalar_one=None)
        result = asyncio_run(get_user_vector(user_id=1, profile_id=999, session=session))
        assert result is None


class TestGetMatchHistory:
    def test_returns_empty_when_no_matches(self):
        session = AsyncMock()
        session.execute.return_value = _mock_execute_result(scalars_all=[])
        result = asyncio_run(get_match_history(user_id=1, session=session))
        assert result == []

    def test_returns_matches_with_analysis(self):
        session = AsyncMock()
        mock_match = MagicMock()
        mock_match.job_profile_id = 1
        mock_match.match_score = 0.85
        mock_match.match_analysis = {
            "vector_similarity": 0.9,
            "dimension_score": 0.8,
            "dimension_matches": {},
            "weights_used": {},
        }
        session.execute.return_value = _mock_execute_result(scalars_all=[mock_match])
        result = asyncio_run(get_match_history(user_id=1, session=session))
        assert len(result) == 1
        assert result[0].match_score == 0.85


class TestCreateFeedback:
    def test_creates_feedback_successfully(self):
        session = AsyncMock()
        mock_match = MagicMock()
        mock_match.user_id = 1
        session.get.return_value = mock_match
        session.flush = AsyncMock()
        session.refresh = AsyncMock()

        request = FeedbackCreateRequest(match_id=1, feedback_type="like", comment="很好")
        with patch("app.domain.services.matching_service.FeedbackResponse") as mock_cls:
            mock_cls.model_validate.return_value = MagicMock()
            result = asyncio_run(create_feedback(user_id=1, request=request, session=session))
            assert result is not None
            mock_cls.model_validate.assert_called_once()

    def test_raises_when_match_not_exists(self):
        session = AsyncMock()
        session.get.return_value = None
        request = FeedbackCreateRequest(match_id=999, feedback_type="like")
        with pytest.raises(ValueError, match="匹配结果不存在"):
            asyncio_run(create_feedback(user_id=1, request=request, session=session))


class TestGetUserFeedbacks:
    def test_returns_empty_when_no_feedbacks(self):
        session = AsyncMock()
        session.execute.return_value = _mock_execute_result(scalars_all=[])
        result = asyncio_run(get_user_feedbacks(user_id=1, session=session))
        assert result == []

    def test_returns_user_feedbacks(self):
        session = AsyncMock()
        mock_feedback = MagicMock()
        mock_feedback.id = 1
        mock_feedback.user_id = 1
        mock_feedback.match_id = 1
        mock_feedback.feedback_type = "like"
        mock_feedback.comment = None
        mock_feedback.created_at = datetime.now()
        session.execute.return_value = _mock_execute_result(scalars_all=[mock_feedback])
        result = asyncio_run(get_user_feedbacks(user_id=1, session=session))
        assert len(result) == 1
