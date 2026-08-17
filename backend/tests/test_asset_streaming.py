from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.api.v1.assets import _etag_matches, _iter_file_range


class AssetStreamingTests(unittest.TestCase):
    def test_streams_only_requested_byte_range(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "asset.bin"
            path.write_bytes(b"0123456789")

            body = b"".join(_iter_file_range(path, start=3, length=4, chunk_size=2))

        self.assertEqual(body, b"3456")

    def test_matches_weak_etag_from_conditional_request(self) -> None:
        etag = 'W/"a-b"'

        self.assertTrue(_etag_matches(etag, etag))
        self.assertTrue(_etag_matches(f'"other", {etag}', etag))
        self.assertTrue(_etag_matches("*", etag))
        self.assertFalse(_etag_matches('W/"other"', etag))


if __name__ == "__main__":
    unittest.main()
