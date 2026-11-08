import base64
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from tls_config import certificate_directory


def restrict_directory(directory):
    identity_script = (
        "[Security.Principal.WindowsIdentity]::GetCurrent().User.Value"
    )
    identity = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", identity_script],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not identity.startswith("S-1-"):
        raise RuntimeError("Could not determine the current Windows user SID.")
    subprocess.run(
        [
            "icacls.exe",
            str(directory),
            "/inheritance:r",
            "/grant:r",
            f"*{identity}:(OI)(CI)F",
            "*S-1-5-18:(OI)(CI)F",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def build_certificates(directory):
    ca_key_path = directory / "ca-key.pem"
    ca_certificate_path = directory / "ca.cer"
    server_key_path = directory / "server-key.pem"
    server_certificate_path = directory / "server.crt"
    existing_paths = (ca_key_path, ca_certificate_path, server_key_path, server_certificate_path)
    if all(path.is_file() for path in existing_paths):
        try:
            ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
            ca_certificate = x509.load_der_x509_certificate(ca_certificate_path.read_bytes())
            server_key = serialization.load_pem_private_key(server_key_path.read_bytes(), password=None)
            server_certificate = x509.load_pem_x509_certificate(server_certificate_path.read_bytes())
            now = datetime.now(timezone.utc)
            if (
                ca_certificate.not_valid_after_utc > now
                and server_certificate.not_valid_after_utc > now + timedelta(days=30)
                and server_certificate.issuer == ca_certificate.subject
                and ca_key.public_key().public_numbers()
                == ca_certificate.public_key().public_numbers()
                and server_key.public_key().public_numbers()
                == server_certificate.public_key().public_numbers()
            ):
                ca_certificate.public_key().verify(
                    server_certificate.signature,
                    server_certificate.tbs_certificate_bytes,
                    padding.PKCS1v15(),
                    server_certificate.signature_hash_algorithm,
                )
                sans = server_certificate.extensions.get_extension_for_class(
                    x509.SubjectAlternativeName
                ).value
                if (
                    ip_address("127.0.0.1") in sans.get_values_for_type(x509.IPAddress)
                    and "localhost" in sans.get_values_for_type(x509.DNSName)
                ):
                    return ca_certificate_path, server_certificate_path, server_key_path
        except (
            ValueError,
            TypeError,
            AttributeError,
            InvalidSignature,
            x509.ExtensionNotFound,
        ):
            pass

    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Lab4 Budikov Local HTTPS CA")]
    )
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")]
    )
    server_certificate = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_certificate.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=397))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.IPAddress(ip_address("127.0.0.1")),
                    x509.DNSName("localhost"),
                ]
            ),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    ca_key_path.write_bytes(
        ca_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    ca_certificate_path.write_bytes(
        ca_certificate.public_bytes(serialization.Encoding.DER)
    )
    server_key_path.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    server_certificate_path.write_bytes(
        server_certificate.public_bytes(serialization.Encoding.PEM)
    )
    return ca_certificate_path, server_certificate_path, server_key_path


def trust_ca(certificate_path):
    certificate = base64.b64encode(certificate_path.read_bytes()).decode("ascii")
    script = (
        "$bytes = [Convert]::FromBase64String('"
        + certificate
        + "'); "
        + "$cert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($bytes); "
        + "$store = [System.Security.Cryptography.X509Certificates.X509Store]::new("
        + "'Root', [System.Security.Cryptography.X509Certificates.StoreLocation]::CurrentUser); "
        + "$store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite); "
        + "try { "
        + "if (-not ($store.Certificates | Where-Object Thumbprint -eq $cert.Thumbprint)) "
        + "{ $store.Add($cert) }; "
        + "$store.Certificates | Where-Object { $_.Subject -eq $cert.Subject -and "
        + "$_.Thumbprint -ne $cert.Thumbprint } | ForEach-Object { $store.Remove($_) }; "
        + "} finally { $store.Close() }"
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
        capture_output=True,
        text=True,
    )


def main():
    if os.name != "nt":
        raise RuntimeError("HTTPS certificate setup is supported on Windows only.")
    directory = certificate_directory()
    directory.mkdir(parents=True, exist_ok=True)
    restrict_directory(directory)
    ca_certificate, server_certificate, server_key = build_certificates(directory)
    trust_ca(ca_certificate)
    print("Local HTTPS certificate is trusted for the current Windows user.")
    print(f"Server certificate: {server_certificate}")
    print(f"Private keys are stored in: {directory}")
    print("Start the application with: python app\\main.py")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        detail = error.stderr or error.stdout or str(error)
        print(f"HTTPS setup failed: {detail.strip()}", file=sys.stderr)
        raise SystemExit(1) from error
    except (OSError, RuntimeError) as error:
        print(f"HTTPS setup failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
