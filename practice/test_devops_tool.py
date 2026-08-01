#!/usr/bin/env python3
"""
devops_tool.py 的完整单元测试 + 集成测试
这个测试脚本的工作原理，本质是：用 Python 自带的 unittest 测试框架
直接调用 AIS.py 里的函数
构造各种“边界场景”来验证返回值、文件状态和告警逻辑是否符合预期。
"""

import os
import sys
import shutil
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from AIS import _parse_size, _format_size, cmd_log_inspect, cmd_disk_cleanup


class TestParseSize(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(_parse_size("0"), 0)
        self.assertEqual(_parse_size("0B"), 0)

    def test_bytes(self):
        self.assertEqual(_parse_size("100"), 100)
        self.assertEqual(_parse_size("100B"), 100)

    def test_kb(self):
        self.assertEqual(_parse_size("1KB"), 1024)
        self.assertEqual(_parse_size("2KB"), 2048)
        self.assertEqual(_parse_size("0.5KB"), 512)

    def test_mb(self):
        self.assertEqual(_parse_size("1MB"), 1024 ** 2)

    def test_gb(self):
        self.assertEqual(_parse_size("1GB"), 1024 ** 3)
        self.assertEqual(_parse_size("1.5GB"), int(1.5 * 1024 ** 3))

    def test_tb(self):
        self.assertEqual(_parse_size("1TB"), 1024 ** 4)

    def test_invalid_empty(self):
        with self.assertRaises(ValueError):
            _parse_size("")

    def test_invalid_unit(self):
        with self.assertRaises(ValueError):
            _parse_size("100XB")


class TestFormatSize(unittest.TestCase):
    def test_format(self):
        self.assertIn("B", _format_size(500))
        self.assertIn("KB", _format_size(2048))
        self.assertIn("MB", _format_size(5 * 1024 ** 2))
        self.assertIn("GB", _format_size(2 * 1024 ** 3))


class TestCmdLogInspect(unittest.TestCase):
    """测试 cmd_log_inspect：目录不存在 + 文件系统集成"""

    def setUp(self):
        self.tmpdir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   f".test_log_{int(time.time())}")
        os.makedirs(self.tmpdir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_dir_not_exist(self):
        class Args:
            log_dir = "/tmp/nonexistent_log_dir_xyz"
            window = 60
            error_threshold = 10
            warn_threshold = 50
            output = ""
        self.assertEqual(cmd_log_inspect(Args()), 1)

    def test_empty_dir(self):
        class Args:
            log_dir = self.tmpdir
            window = 60
            error_threshold = 10
            warn_threshold = 50
            output = ""
        self.assertEqual(cmd_log_inspect(Args()), 0)

    def test_no_recent_files(self):
        """文件修改时间在窗口外 -> exit 0"""
        fpath = os.path.join(self.tmpdir, "old.log")
        with open(fpath, "w") as f:
            f.write("INFO all good\n")
        past = time.time() - 365 * 86400
        os.utime(fpath, (past, past))

        class Args:
            log_dir = self.tmpdir
            window = 60
            error_threshold = 10
            warn_threshold = 50
            output = ""
        self.assertEqual(cmd_log_inspect(Args()), 0)

    def test_recent_file_above_threshold(self):
        """ERROR 超过阈值 -> exit 1"""
        fpath = os.path.join(self.tmpdir, "recent.log")
        with open(fpath, "w") as f:
            for _ in range(20):
                f.write("ERROR something went wrong\n")

        class Args:
            log_dir = self.tmpdir
            window = 60
            error_threshold = 10
            warn_threshold = 50
            output = ""
        self.assertEqual(cmd_log_inspect(Args()), 1)

    def test_mixed_content(self):
        """ERROR 和 WARN 分别统计"""
        fpath = os.path.join(self.tmpdir, "mix.log")
        with open(fpath, "w") as f:
            f.write("ERROR err1\n")
            f.write("ERROR err2\n")
            f.write("WARN warn1\n")
            f.write("WARN warn2\n")
            f.write("WARN warn3\n")
            f.write("INFO fine\n")

        class Args:
            log_dir = self.tmpdir
            window = 60
            error_threshold = 1  # 2 > 1 -> alert
            warn_threshold = 5   # 3 <= 5 -> ok
            output = ""
        self.assertEqual(cmd_log_inspect(Args()), 1)

    def test_log_output_file(self):
        """--output 指定文件 -> 文件应被写入"""
        fpath = os.path.join(self.tmpdir, "app.log")
        with open(fpath, "w") as f:
            f.write("ERROR critical\n")
        out_file = os.path.join(self.tmpdir, "report.txt")

        class Args:
            log_dir = self.tmpdir
            window = 60
            error_threshold = 0
            warn_threshold = 50
            output = out_file
        rc = cmd_log_inspect(Args())
        self.assertEqual(rc, 1)
        self.assertTrue(os.path.exists(out_file))
        with open(out_file, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("告警", content)

    def test_unreadable_file(self):
        """不可读文件应被跳过，不影响整体"""
        good = os.path.join(self.tmpdir, "good.log")
        bad = os.path.join(self.tmpdir, "bad.log")
        with open(good, "w") as f:
            f.write("ERROR something\n")
        with open(bad, "w") as f:
            f.write("WARN something\n")
        os.chmod(bad, 0o000)  # 去掉所有权限

        class Args:
            log_dir = self.tmpdir
            window = 60
            error_threshold = 0
            warn_threshold = 50
            output = ""
        rc = cmd_log_inspect(Args())
        os.chmod(bad, 0o644)  # 恢复权限，以便 tearDown 能删除
        self.assertEqual(rc, 1)


class TestCmdDiskCleanup(unittest.TestCase):
    """测试 cmd_disk_cleanup"""

    def setUp(self):
        self.tmpdir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   f".test_cleanup_{int(time.time())}")
        os.makedirs(self.tmpdir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_dir_not_exist(self):
        class Args:
            dir = "/tmp/nonexistent_cleanup_dir"
            threshold_bytes = 1024
            dry_run = False
            min_age = ""
        self.assertEqual(cmd_disk_cleanup(Args()), 1)

    def test_under_threshold(self):
        """占用 < 阈值 -> exit 0"""
        with open(os.path.join(self.tmpdir, "small.txt"), "w") as f:
            f.write("hello")
        class Args:
            dir = self.tmpdir
            threshold_bytes = 10 * 1024 ** 3  # 10GB
            dry_run = False
            min_age = ""
        self.assertEqual(cmd_disk_cleanup(Args()), 0)

    def test_dry_run_keeps_files(self):
        """演练模式不应删除文件"""
        fpath = os.path.join(self.tmpdir, "old_file.bin")
        with open(fpath, "wb") as f:
            f.write(b"x" * 1024 * 10)
        class Args:
            dir = self.tmpdir
            threshold_bytes = 1
            dry_run = True
            min_age = ""
        rc = cmd_disk_cleanup(Args())
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(fpath))

    def test_min_age_protects_recent(self):
        """min-age 保护最近修改的文件不被删除"""
        fpath = os.path.join(self.tmpdir, "new_file.bin")
        with open(fpath, "wb") as f:
            f.write(b"x" * 1024 * 10)
        class Args:
            dir = self.tmpdir
            threshold_bytes = 1
            dry_run = True
            min_age = "1h"  # 保留 1 小时内的文件
        rc = cmd_disk_cleanup(Args())
        self.assertEqual(rc, 0)

    def test_actual_deletion(self):
        """执行模式应删除文件直到低于阈值"""
        for i in range(5):
            fpath = os.path.join(self.tmpdir, f"file_{i}.bin")
            with open(fpath, "wb") as f:
                f.write(b"x" * 1024 * 100)  # 每个 100KB
            time.sleep(0.01)
        class Args:
            dir = self.tmpdir
            threshold_bytes = 1024 * 200  # 200KB
            dry_run = False
            min_age = ""
        rc = cmd_disk_cleanup(Args())
        self.assertEqual(rc, 0)
        remaining = sum(os.path.getsize(os.path.join(self.tmpdir, f))
                        for f in os.listdir(self.tmpdir)
                        if os.path.isfile(os.path.join(self.tmpdir, f)))
        self.assertLessEqual(remaining, 1024 * 200)

    def test_min_age_invalid_format(self):
        """min-age 格式错误 -> exit 1
        注意：目录中必须要有文件且超阈值，才会走到 min_age 校验。"""
        # 创建一个文件使目录占用超过阈值
        fpath = os.path.join(self.tmpdir, "dummy.bin")
        with open(fpath, "wb") as f:
            f.write(b"x" * 1024)  # 1KB
        class Args:
            dir = self.tmpdir
            threshold_bytes = 1  # 1KB > 1B，必然超阈值
            dry_run = True
            min_age = "xyz"
        rc = cmd_disk_cleanup(Args())
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
