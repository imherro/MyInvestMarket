from __future__ import annotations

import sys
import tempfile
import time
import unittest
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_post_close_update  # noqa: E402


class PostCloseLockTest(unittest.TestCase):
    def test_second_update_safely_skips_when_lock_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_path = Path(tmp_dir) / "post_close_update.lock"
            first = run_post_close_update.acquire_post_close_lock(lock_path)
            try:
                second = run_post_close_update.acquire_post_close_lock(lock_path)
            finally:
                run_post_close_update.release_post_close_lock(first)

        self.assertTrue(first["acquired"])
        self.assertFalse(second["acquired"])
        self.assertEqual(second["reason"], "post-close update already running")
        self.assertIn("existing_pid", second)

    def test_lock_can_be_reacquired_after_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_path = Path(tmp_dir) / "post_close_update.lock"
            first = run_post_close_update.acquire_post_close_lock(lock_path)
            run_post_close_update.release_post_close_lock(first)
            second = run_post_close_update.acquire_post_close_lock(lock_path)
            try:
                self.assertTrue(second["acquired"])
            finally:
                run_post_close_update.release_post_close_lock(second)

    def test_stale_lock_is_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_path = Path(tmp_dir) / "post_close_update.lock"
            lock_path.write_text('{"pid": 1, "started_at": "2000-01-01T00:00:00+08:00"}\n', encoding="utf-8")
            old_time = time.time() - 120
            os.utime(lock_path, (old_time, old_time))
            lock = run_post_close_update.acquire_post_close_lock(lock_path, stale_seconds=1)
            try:
                self.assertTrue(lock["acquired"])
            finally:
                run_post_close_update.release_post_close_lock(lock)


if __name__ == "__main__":
    unittest.main()
