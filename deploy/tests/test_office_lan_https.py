import importlib.util
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

spec = importlib.util.spec_from_file_location('office_lan_https', Path(__file__).parents[1] / 'office_lan_https.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def certificate(root, name=module.DOMAIN, days=30, mismatch=False):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=days)).add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
            .sign(key, hashes.SHA256()))
    folder = root / 'certs'
    folder.mkdir()
    (folder / 'fullchain.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    if mismatch:
        key = ec.generate_private_key(ec.SECP256R1())
    (folder / 'privkey.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


def test_configuration_preserves_local_upstream_and_no_other_listeners(tmp_path):
    config = module.configuration('192.168.101.193', tmp_path)
    assert 'bind 192.168.101.193' in config
    assert 'reverse_proxy 127.0.0.1:8001' in config
    assert 'auto_https off' in config and 'admin off' in config
    assert 'tls_insecure_skip_verify' not in config


@pytest.mark.parametrize('change', [{'address':'8.8.8.8'}, {'address':'127.0.0.1'}, {'subnet':'0.0.0.0/0'}, {'backend_port':8002}, {'unexpected':True}])
def test_invalid_plan_rejected_before_windows_mutations(tmp_path, change):
    root = tmp_path / 'backend/app'
    root.mkdir(parents=True)
    (root / 'main.py').touch()
    plan = {'live_root':str(tmp_path), 'address':'192.168.101.193', 'subnet':'192.168.100.0/23', 'backend_port':8001, **change}
    with pytest.raises(ValueError):
        module.validate_plan(plan)


@pytest.mark.parametrize('kwargs', [{'name':'other.example'}, {'days':1}, {'mismatch':True}])
def test_invalid_certificate_rejected(tmp_path, kwargs):
    certificate(tmp_path, **kwargs)
    with pytest.raises(ValueError):
        module.validate_certificate(tmp_path)


def test_matching_certificate_preflight(tmp_path):
    certificate(tmp_path)
    assert module.validate_certificate(tmp_path)


def test_config_rejects_newline_in_paths(tmp_path):
    with pytest.raises(ValueError):
        module.configuration('192.168.101.193', tmp_path / 'bad\npath')
