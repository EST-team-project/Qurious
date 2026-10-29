"""DB 백업 파일 암호화/복원. 출력 파일은 새로 만들며 키·내용은 출력하지 않는다."""
import argparse
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.lib.broker_secrets import keyring, CredentialStorageError

PREFIX = b"QDB1\x00"
LIMIT = 256 * 1024 * 1024


def seal(data):
    kid, keys = keyring()
    header = PREFIX + kid.encode() + b"\x00"
    nonce = os.urandom(12)
    return header + nonce + AESGCM(keys[kid]).encrypt(nonce, data, header)


def unseal(data):
    try:
        if not data.startswith(PREFIX):
            raise ValueError
        kid, body = data[len(PREFIX):].split(b"\x00", 1)
        header = PREFIX + kid + b"\x00"
        _, keys = keyring()
        return AESGCM(keys[kid.decode()]).decrypt(body[:12], body[12:], header)
    except Exception:
        raise CredentialStorageError() from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--decrypt", action="store_true")
    args = parser.parse_args()
    if args.input.stat().st_size > LIMIT:
        parser.error("256 MiB 이하 백업만 이 도구로 처리할 수 있습니다.")
    data = args.input.read_bytes()
    result = unseal(data) if args.decrypt else seal(data)
    if not args.decrypt and unseal(result) != data:
        raise CredentialStorageError()
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(result)
    print("복원 완료" if args.decrypt else "암호화 및 왕복 검증 완료")


if __name__ == "__main__":
    main()
