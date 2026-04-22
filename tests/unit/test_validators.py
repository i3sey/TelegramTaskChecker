import pytest
from src.bot.utils.validators import (
    validate_file_extension,
    validate_file_size,
    validate_file,
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
)


def test_validate_file_extension_pdf():
    assert validate_file_extension("document.pdf") == True


def test_validate_file_extension_invalid():
    assert validate_file_extension("virus.exe") == False


def test_validate_file_size_valid():
    assert validate_file_size(1024 * 1024) == True  # 1MB


def test_validate_file_size_too_large():
    assert validate_file_size(100 * 1024 * 1024) == False  # 100MB


def test_validate_file_extension_docx():
    assert validate_file_extension("report.docx") == True


def test_validate_file_extension_txt():
    assert validate_file_extension("readme.txt") == True


def test_validate_file_extension_jpg():
    assert validate_file_extension("photo.jpg") == True


def test_validate_file_extension_png():
    assert validate_file_extension("image.png") == True


def test_validate_file_extension_case_insensitive():
    assert validate_file_extension("DOCUMENT.PDF") == True
    assert validate_file_extension("Document.Pdf") == True


def test_validate_file_extension_not_allowed():
    assert validate_file_extension("script.js") == False
    assert validate_file_extension("archive.zip") == False


def test_validate_file_size_exactly_at_limit():
    # MAX_FILE_SIZE is 50 MB
    assert validate_file_size(MAX_FILE_SIZE) == True


def test_validate_file_size_just_above_limit():
    # 1 byte above limit
    assert validate_file_size(MAX_FILE_SIZE + 1) == False


def test_validate_file_size_zero():
    assert validate_file_size(0) == True


def test_validate_file_valid():
    is_valid, error = validate_file("document.pdf", 1024 * 1024)
    assert is_valid == True
    assert error is None


def test_validate_file_invalid_extension():
    is_valid, error = validate_file("virus.exe", 1024)
    assert is_valid == False
    assert "формат" in error.lower() or "format" in error.lower()


def test_validate_file_too_large():
    is_valid, error = validate_file("document.pdf", 100 * 1024 * 1024)
    assert is_valid == False
    assert "большой" in error.lower() or "large" in error.lower()


def test_allowed_extensions_contains_expected_values():
    assert ".pdf" in ALLOWED_EXTENSIONS
    assert ".docx" in ALLOWED_EXTENSIONS
    assert ".txt" in ALLOWED_EXTENSIONS
    assert ".jpg" in ALLOWED_EXTENSIONS
    assert ".png" in ALLOWED_EXTENSIONS


def test_max_file_size_is_50mb():
    assert MAX_FILE_SIZE == 50 * 1024 * 1024