"""Encrypt and restore delivery history stored in a public repository."""

import argparse
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


def _cipher() -> Fernet:
    key = os.environ.get("BOT_STATE_KEY", "")
    if not key:
        raise ValueError("BOT_STATE_KEY is required for encrypted delivery history")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ValueError("BOT_STATE_KEY must be a valid Fernet key") from exc


def encrypt_state(source: Path, destination: Path) -> None:
    """Write authenticated ciphertext without changing the plaintext database."""
    cipher = _cipher()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(cipher.encrypt(source.read_bytes()))


def decrypt_state(source: Path, destination: Path) -> None:
    """Restore a database only when the ciphertext authenticates successfully."""
    cipher = _cipher()
    try:
        plaintext = cipher.decrypt(source.read_bytes())
    except InvalidToken as exc:
        raise ValueError("delivery history could not be decrypted with BOT_STATE_KEY") from exc
    if not plaintext.startswith(b"SQLite format 3\x00"):
        raise ValueError("decrypted delivery history is not a SQLite database")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(plaintext)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("encrypt", "decrypt"))
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.operation == "encrypt":
        encrypt_state(args.source, args.destination)
    else:
        decrypt_state(args.source, args.destination)


if __name__ == "__main__":
    main()
