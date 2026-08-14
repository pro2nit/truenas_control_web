from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from nas_control.config import Config


class ConfigTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            config = Config()
            config.save(path)
            loaded = Config.load(path)
            self.assertEqual(loaded.nas_ip, "192.168.1.100")
            self.assertEqual(loaded.listen_host, "127.0.0.1")

    def test_rejects_public_bind(self) -> None:
        config = Config(listen_host="0.0.0.0")
        with self.assertRaises(ValueError):
            config.validate()

    def test_accepts_tailscale_bind(self) -> None:
        config = Config(listen_host="100.64.0.10")
        config.validate()


if __name__ == "__main__":
    unittest.main()
