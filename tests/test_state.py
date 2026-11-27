"""Encrypted delivery history survives a round trip and rejects wrong keys."""

import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from internship_bot.state import decrypt_state, encrypt_state


def test_encrypted_state_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = tmp_path / "jobs.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, sent_at TEXT)")
        connection.execute("INSERT INTO jobs (sent_at) VALUES ('2026-11-23')")
    original = database.read_bytes()
    encrypted = tmp_path / "jobs.sqlite3.enc"
    restored = tmp_path / "restored.sqlite3"
    monkeypatch.setenv("BOT_STATE_KEY", Fernet.generate_key().decode())
    encrypt_state(database, encrypted)
    assert encrypted.read_bytes() != original
    decrypt_state(encrypted, restored)
    assert restored.read_bytes() == original

    monkeypatch.setenv("BOT_STATE_KEY", Fernet.generate_key().decode())
    with pytest.raises(ValueError, match="could not be decrypted"):
        decrypt_state(encrypted, restored)
