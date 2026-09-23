"""자체 서명 인증서 생성.

getUserMedia 는 **보안 컨텍스트(HTTPS)** 에서만 동작한다. localhost 는 예외지만
폰은 LAN IP 로 접속하므로 예외에 걸리지 않는다. 그래서 HTTP 로는 폰 카메라를
아예 열 수 없고, 자체 서명 인증서라도 반드시 필요하다.

폰 브라우저는 "이 사이트는 안전하지 않습니다" 경고를 띄운다. 한 번 통과시키면
된다 (Chrome: 고급 → 계속). 경고를 없애려면 인증서를 폰에 설치해야 하는데,
촬영 한 판에 그만한 가치는 없다.
"""

from __future__ import annotations

import datetime as _dt
import ipaddress
import socket
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

CERT_FILENAME = "cert.pem"
KEY_FILENAME = "key.pem"

#: 인증서 유효기간 (일). 촬영 한 회차에 충분하고, 오래 끌면 잊고 쓰게 된다.
CERT_VALID_DAYS = 365

#: RSA 키 길이.
RSA_KEY_BITS = 2048


def lan_ip() -> str:
    """이 노트북이 LAN 에서 갖는 IP.

    UDP 소켓을 열어 라우팅 테이블이 고르는 출발지 주소를 읽는다.
    실제로 패킷을 보내지는 않는다 (UDP connect 는 통신을 일으키지 않는다).
    Wi-Fi 가 없으면 127.0.0.1 로 떨어진다 - 그러면 폰에서 접속할 수 없다.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return str(sock.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def ensure_certs(certs_dir: Path, extra_ip: str | None = None) -> tuple[Path, Path]:
    """certs_dir 에 cert.pem, key.pem 이 없으면 만든다. 있으면 그대로 쓴다.

    SAN(Subject Alternative Name)에 localhost, 127.0.0.1, 그리고 현재 LAN IP 를
    넣는다. **IP 가 바뀌면(다른 Wi-Fi, DHCP 갱신) 인증서를 다시 만들어야 한다** -
    SAN 에 없는 주소로 접속하면 브라우저가 더 강하게 막는다.

    Returns:
        (cert_path, key_path)
    """
    certs_dir = Path(certs_dir)
    cert_path = certs_dir / CERT_FILENAME
    key_path = certs_dir / KEY_FILENAME
    if cert_path.exists() and key_path.exists():
        return cert_path, key_path

    certs_dir.mkdir(parents=True, exist_ok=True)
    ip = extra_ip or lan_ip()

    key = rsa.generate_private_key(public_exponent=65537, key_size=RSA_KEY_BITS)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, ip),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "camcal s10 capture"),
        ]
    )

    san = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    try:
        san.append(x509.IPAddress(ipaddress.ip_address(ip)))
    except ValueError:  # pragma: no cover - lan_ip 는 항상 유효한 IPv4 를 준다
        pass

    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=5))  # 시계 오차 여유
        .not_valid_after(now + _dt.timedelta(days=CERT_VALID_DAYS))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .sign(key, hashes.SHA256())
    )

    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


def cert_san_ips(cert_path: Path) -> list[str]:
    """인증서에 들어 있는 IP 목록. 지금 LAN IP 와 다른지 확인하는 데 쓴다."""
    cert = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        return []
    return [str(ip) for ip in ext.value.get_values_for_type(x509.IPAddress)]
