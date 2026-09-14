import base64
import os
import tempfile

import pytest

from internal.core.vision.vision_invoke import path_to_data_uri


def test_path_to_data_uri_encodes_file_bytes():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = os.path.join(temp_dir, "sample.jpg")
        with open(path, "wb") as fh:
            fh.write(b"\xff\xd8\xff\xe0hello")

        data_uri = path_to_data_uri(path)

    assert data_uri.startswith("data:image/jpeg;base64,")
    encoded = data_uri.split(",", 1)[1]
    assert base64.b64decode(encoded) == b"\xff\xd8\xff\xe0hello"


def test_path_to_data_uri_rejects_oversized_file(monkeypatch):
    import internal.core.vision.vision_invoke as module

    monkeypatch.setattr(module, "_MAX_IMAGE_BYTES", 4)
    with tempfile.TemporaryDirectory() as temp_dir:
        path = os.path.join(temp_dir, "big.jpg")
        with open(path, "wb") as fh:
            fh.write(b"12345")

        with pytest.raises(ValueError):
            path_to_data_uri(path)
