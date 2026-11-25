"""Bound cloud action decoding before JSON/model validation; no cloud or CFD calls."""

from __future__ import annotations

import base64
import gzip
import json
import zlib
from pathlib import Path

import pytest

from discovery_physics import service


def encoded(data: bytes) -> str:
    return base64.b64encode(gzip.compress(data, mtime=0)).decode("ascii")


@pytest.mark.parametrize("compressed", [False, True])
def test_decode_accepts_utf8_object(compressed):
    value = {"name": "flow-\u03bb", "members": [{"value": 3.0}]}
    text = json.dumps(value, ensure_ascii=False)
    assert service._decode(encoded(text.encode()) if compressed else None,
                           None if compressed else text) == value


@pytest.mark.parametrize("name", ["channel-path-check.json", "cases/nz.json"])
def test_curated_action_payloads_remain_supported(name):
    root = Path(__file__).resolve().parents[1] / "examples"
    path = root / name
    if not path.is_file():
        path = next(root.rglob(Path(name).name))
    raw = path.read_bytes()
    payload = encoded(raw)
    assert len(payload) <= 65536
    assert service._decode(payload, None) == json.loads(raw)


def test_decode_refuses_expansion_before_json(monkeypatch):
    monkeypatch.setattr(service, "MAX_PAYLOAD_BYTES", 1024, raising=False)
    payload = encoded(b'{"data":"' + b"x" * 2048 + b'"}')
    monkeypatch.setattr(service.json, "loads", lambda *a, **k: pytest.fail("Oversize input reached JSON parsing."))
    with pytest.raises(ValueError, match="exceeds"):
        service._decode(payload, None)


def test_high_ratio_payload_exceeds_production_bound():
    payload = encoded(b'{"data":"' + b"x" * (16 * 1024 * 1024 + 1) + b'"}')
    assert len(payload) < 65536
    with pytest.raises(ValueError, match="exceeds"):
        service._decode(payload, None)


@pytest.mark.parametrize("compressed", [False, True])
def test_decoded_limit_counts_utf8_bytes_and_accepts_exact_boundary(monkeypatch, compressed):
    text = json.dumps({"data": "\u03bb" * 16}, ensure_ascii=False)
    size = len(text.encode("utf-8"))
    args = (encoded(text.encode()), None) if compressed else (None, text)
    monkeypatch.setattr(service, "MAX_PAYLOAD_BYTES", size, raising=False)
    assert service._decode(*args) == {"data": "\u03bb" * 16}
    monkeypatch.setattr(service, "MAX_PAYLOAD_BYTES", size - 1)
    with pytest.raises(ValueError, match="exceeds"):
        service._decode(*args)


@pytest.mark.parametrize("tail", [b"garbage", b"\x00", gzip.compress(b" "), gzip.compress(b"{}")])
def test_decode_rejects_every_trailing_compressed_byte(tail):
    payload = base64.b64encode(gzip.compress(b"{}") + tail).decode()
    with pytest.raises(ValueError, match="gzip|trailing"):
        service._decode(payload, None)


@pytest.mark.parametrize("fault", ["empty", "not-gzip", "header", "truncated", "checksum"])
def test_malformed_or_incomplete_gzip_is_rejected(fault):
    raw = gzip.compress(b'{"ok":true}', mtime=0)
    malformed = {
        "empty": b"", "not-gzip": b"not gzip", "header": raw[:8],
        "truncated": raw[:-1], "checksum": raw[:-8] + bytes([raw[-8] ^ 1]) + raw[-7:],
    }[fault]
    with pytest.raises(ValueError, match="gzip|required"):
        service._decode(base64.b64encode(malformed).decode(), None)


@pytest.mark.parametrize("payload", ["!not_base64!", "e30=\n", "e30", "\u03bb"])
def test_base64_is_strict(payload):
    with pytest.raises(ValueError):
        service._decode(payload, None)


def test_encoded_length_is_checked_before_base64_decode(monkeypatch):
    monkeypatch.setattr(service.base64, "b64decode", lambda *a, **k: pytest.fail("Oversize encoded input was decoded."))
    with pytest.raises(ValueError, match="65536"):
        service._decode("A" * 65540, None)


@pytest.mark.parametrize("raw", [b"[]", b"null", b"1", b'"text"', b"{} {}", b"{", b"\xff"])
def test_payload_must_be_one_utf8_json_object(raw):
    with pytest.raises(ValueError):
        service._decode(encoded(raw), None)


def test_decompressor_is_always_given_a_finite_output_bound(monkeypatch):
    real = zlib.decompressobj
    calls = []

    class Bounded:
        def __init__(self, *args, **kwargs):
            self.decoder = real(*args, **kwargs)

        def decompress(self, data, max_length=0):
            assert 0 < max_length <= service.MAX_PAYLOAD_BYTES + 1
            calls.append(max_length)
            return self.decoder.decompress(data, max_length)

        def __getattr__(self, name):
            assert name != "flush", "Do not finish with an unbounded allocation."
            return getattr(self.decoder, name)

    monkeypatch.setattr(service.zlib, "decompressobj", Bounded)
    assert service._decode(encoded(b"{}"), None) == {}
    assert calls


@pytest.mark.parametrize("action,flag", [("evaluate", "--bundle-b64gz"), ("study", "--spec-b64gz"),
                                         ("lint", "--bundle-b64gz")])
def test_service_reports_decode_refusal_before_any_runner_action(action, flag, tmp_path, monkeypatch):
    from discovery_physics.openfoam import runner, study

    monkeypatch.setattr(service, "OUTPUT", tmp_path / "output")
    monkeypatch.setattr(service, "MAX_PAYLOAD_BYTES", 128, raising=False)
    for symbol in ("prepare", "lint_bundle", "execute"):
        monkeypatch.setattr(runner, symbol, lambda *a, **k: pytest.fail("Refused payload reached runner."))
    monkeypatch.setattr(study, "prepare", lambda *a, **k: pytest.fail("Refused payload staged a study."))
    for name in ("DISCOVERY_PHYSICS_IN_CONTAINER", "DISCOVERY_PHYSICS_RUNS", "DISCOVERY_PHYSICS_KEY_FILE", "LOCALAPPDATA"):
        monkeypatch.setenv(name, str(tmp_path / name))
    assert service.main([action, flag, encoded(b'{"data":"' + b"x" * 256 + b'"}')]) == 2
    result = json.loads((tmp_path / "output/result.json").read_text(encoding="utf-8"))
    assert result["error"] == "ValueError" and "exceeds" in result["detail"]


def test_missing_payload_is_a_reported_value_error():
    with pytest.raises(ValueError, match="required"):
        service._decode(None, None)