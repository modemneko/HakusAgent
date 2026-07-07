"""
工作空间管理 - 管理项目目录结构
"""

from pathlib import Path
from typing import Optional
from ...schema.models import ProjectConfig


class Workspace:
    """工作空间"""
    
    def __init__(self, root_path: str):
        self.root_path = Path(root_path)
        self.doc_dir = self.root_path / "doc"
        self.src_dir = self.root_path / "src"
        self.logs_dir = self.root_path / "logs"
        self.test_reports_dir = self.root_path / "test-reports"
    
    def ensure_directories(self):
        """确保目录结构存在"""
        self.doc_dir.mkdir(exist_ok=True)
        self.src_dir.mkdir(exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)
        self.test_reports_dir.mkdir(exist_ok=True)
    
    def write_plan(self, plan: str):
        """写入计划"""
        plan_file = self.doc_dir / "plan.md"
        plan_file.write_text(plan, encoding='utf-8')
    
    def read_plan(self) -> Optional[str]:
        """读取计划"""
        plan_file = self.doc_dir / "plan.md"
        if plan_file.exists():
            return plan_file.read_text(encoding='utf-8')
        return None
    
    def append_log(self, log: str):
        """追加日志"""
        log_file = self.logs_dir / "execution.log"
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"{log}\n")
    
    def write_test_report(self, report: str, name: str = "latest"):
        """写入测试报告"""
        report_file = self.test_reports_dir / f"{name}.md"
        report_file.write_text(report, encoding='utf-8')