import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from freemad import load_config, AgentConfig, AgentRuntimeConfig
from freemad import CLIAdapter, DiskCache


class TestDiskCacheIntegration(unittest.TestCase):
    def test_cli_adapter_uses_cache_when_enabled(self):
        # Prepare config overrides enabling cache
        exe = sys.executable
        overrides = {
            "cache": {"enabled": True, "dir": ".mad_cache_test", "max_entries": 50},
            "security": {"cli_allowed_commands": [exe]},
        }
        cfg = load_config(overrides=overrides)
        agent_cfg = AgentConfig(
            id="mock",
            type="openai_codex",
            enabled=True,
            cli_command=f"{exe} bin/mock_agent.py",
            timeout=2.0,
            config=AgentRuntimeConfig(temperature=0.0, max_tokens=256),
        )
        adapter = CLIAdapter(cfg, agent_cfg)
        # First call should populate cache
        r1 = adapter.generate("do something")
        self.assertIn("elapsed_ms", r1.metadata.timings)
        # Second call should hit cache (timings.cached == 1.0)
        r2 = adapter.generate("do something")
        self.assertEqual(r2.metadata.timings.get("cached"), 1.0)
        # Cleanup cache dir
        Path(cfg.cache.dir).mkdir(parents=True, exist_ok=True)
        for p in Path(cfg.cache.dir).glob("*.json"):
            try:
                p.unlink()
            except Exception:
                pass
        try:
            os.rmdir(cfg.cache.dir)
        except Exception:
            pass

    def test_eviction_respects_max_entries(self):
        with tempfile.TemporaryDirectory() as td:
            cache = DiskCache(dir=td, max_entries=1)
            cache.set("k1", "v1")
            time.sleep(0.01)
            cache.set("k2", "v2")
            files = list(Path(td).glob("*.json"))
            # only most recent should remain
            assert len(files) == 1
            val = cache.get("k2")
            assert val == "v2"


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
