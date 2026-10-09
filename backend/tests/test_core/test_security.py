"""Tests for infrastructure/security.py — JWT and password hashing."""

from datetime import datetime, timedelta, timezone

from app.infrastructure.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_password_returns_string(self):
        hashed = hash_password("testpassword123")
        assert isinstance(hashed, str)
        assert len(hashed) > 0

    def test_hash_password_different_each_time(self):
        password = "same_password"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        assert hash1 != hash2

    def test_verify_password_correct(self):
        password = "correct_password"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        password = "correct_password"
        wrong_password = "wrong_password"
        hashed = hash_password(password)
        assert verify_password(wrong_password, hashed) is False

    def test_verify_password_empty_string(self):
        hashed = hash_password("some_password")
        assert verify_password("", hashed) is False


class TestJWTToken:
    def test_create_access_token_returns_string(self):
        token = create_access_token({"sub": "user123"})
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_access_token_with_custom_expiry(self):
        token = create_access_token({"sub": "user123"}, expires_delta=timedelta(minutes=5))
        assert isinstance(token, str)

    def test_decode_access_token_valid(self):
        data = {"sub": "user123", "role": "admin"}
        token = create_access_token(data)
        decoded = decode_access_token(token)
        assert decoded is not None
        assert decoded["sub"] == "user123"
        assert decoded["role"] == "admin"
        assert "exp" in decoded

    def test_decode_access_token_invalid(self):
        result = decode_access_token("invalid.token.here")
        assert result is None

    def test_decode_access_token_empty_string(self):
        result = decode_access_token("")
        assert result is None

    def test_decode_access_token_tampered(self):
        data = {"sub": "user123"}
        token = create_access_token(data)
        tampered = token[:-5] + "XXXXX"
        result = decode_access_token(tampered)
        assert result is None

    def test_token_expiry_in_future(self):
        data = {"sub": "user123"}
        token = create_access_token(data, expires_delta=timedelta(hours=1))
        decoded = decode_access_token(token)
        assert decoded is not None
        exp_timestamp = decoded["exp"]
        now = datetime.now(timezone.utc).timestamp()
        assert exp_timestamp > now

    def test_create_token_with_empty_data(self):
        token = create_access_token({})
        decoded = decode_access_token(token)
        assert decoded is not None
        assert "exp" in decoded
