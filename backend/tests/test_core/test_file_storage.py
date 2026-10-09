"""Tests for utils/file_storage.py — file hash and upload storage."""

from pathlib import Path
from unittest.mock import patch

from app.utils.file_storage import compute_file_hash, save_upload_file


class TestComputeFileHash:
    def test_compute_hash_returns_hex_string(self):
        file_bytes = b"test file content"
        result = compute_file_hash(file_bytes)
        assert isinstance(result, str)
        assert len(result) == 64

    def test_compute_hash_deterministic(self):
        file_bytes = b"same content"
        hash1 = compute_file_hash(file_bytes)
        hash2 = compute_file_hash(file_bytes)
        assert hash1 == hash2

    def test_compute_hash_different_content(self):
        hash1 = compute_file_hash(b"content A")
        hash2 = compute_file_hash(b"content B")
        assert hash1 != hash2

    def test_compute_hash_empty_bytes(self):
        result = compute_file_hash(b"")
        assert isinstance(result, str)
        assert len(result) == 64


class TestSaveUploadFile:
    def test_save_file_creates_directory(self, tmp_path):
        with patch("app.utils.file_storage.get_settings") as mock_settings:
            mock_settings.return_value.upload_dir = str(tmp_path)
            file_path, content_hash = save_upload_file(b"test content", 1, "test.pdf")

            expected_dir = tmp_path / "user_1"
            assert expected_dir.exists()
            assert Path(file_path).parent == expected_dir

    def test_save_file_returns_valid_path(self, tmp_path):
        with patch("app.utils.file_storage.get_settings") as mock_settings:
            mock_settings.return_value.upload_dir = str(tmp_path)
            file_path, content_hash = save_upload_file(b"test content", 1, "test.pdf")

            assert Path(file_path).exists()
            assert Path(file_path).read_bytes() == b"test content"

    def test_save_file_uses_uuid_filename(self, tmp_path):
        with patch("app.utils.file_storage.get_settings") as mock_settings:
            mock_settings.return_value.upload_dir = str(tmp_path)
            file_path, _ = save_upload_file(b"test content", 1, "test.pdf")

            filename = Path(file_path).stem
            assert len(filename) == 32

    def test_save_file_preserves_extension(self, tmp_path):
        with patch("app.utils.file_storage.get_settings") as mock_settings:
            mock_settings.return_value.upload_dir = str(tmp_path)
            file_path, _ = save_upload_file(b"test content", 1, "document.PDF")

            assert file_path.endswith(".pdf")

    def test_save_file_defaults_to_pdf_extension(self, tmp_path):
        with patch("app.utils.file_storage.get_settings") as mock_settings:
            mock_settings.return_value.upload_dir = str(tmp_path)
            file_path, _ = save_upload_file(b"test content", 1, "noextension")

            assert file_path.endswith(".pdf")

    def test_save_file_returns_correct_hash(self, tmp_path):
        with patch("app.utils.file_storage.get_settings") as mock_settings:
            mock_settings.return_value.upload_dir = str(tmp_path)
            file_path, content_hash = save_upload_file(b"test content", 1, "test.pdf")

            expected_hash = compute_file_hash(b"test content")
            assert content_hash == expected_hash

    def test_save_file_different_users(self, tmp_path):
        with patch("app.utils.file_storage.get_settings") as mock_settings:
            mock_settings.return_value.upload_dir = str(tmp_path)
            path1, _ = save_upload_file(b"content 1", 1, "test.pdf")
            path2, _ = save_upload_file(b"content 2", 2, "test.pdf")

            assert "user_1" in path1
            assert "user_2" in path2
