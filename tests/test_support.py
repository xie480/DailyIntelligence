"""测试共用的临时目录工具。"""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
from typing import Any
import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _ManualTemporaryDirectory:
    """在测试沙箱拒绝 tempfile ACL 时提供随机目录回退。"""

    def __init__(
        self,
        prefix: str,
    ) -> None:
        """在项目目录创建不固定名称的隔离目录。"""
        self.path = PROJECT_ROOT / (
            f"{prefix}{uuid.uuid4().hex}"
        )
        self.path.mkdir(
            parents=False,
            exist_ok=False,
        )
        self.name = str(self.path)

    def cleanup(self) -> None:
        """关闭并递归删除当前测试目录。"""
        shutil.rmtree(
            self.path,
            ignore_errors=True,
        )


def temporary_directory(
    prefix: str,
) -> Any:
    """优先使用系统临时目录，受限环境下回退到随机项目目录。"""
    candidate = tempfile.TemporaryDirectory(
        prefix=prefix,
    )
    try:
        probe_path = Path(candidate.name) / ".write-probe"
        probe_path.write_text(
            "probe",
            encoding="utf-8",
        )
        probe_path.unlink()
        return candidate
    except OSError:
        try:
            candidate.cleanup()
        except OSError:
            pass
        return _ManualTemporaryDirectory(
            prefix,
        )
