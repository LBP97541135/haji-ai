"""
Sandbox 模块数据结构定义。

定义沙箱执行结果、代码产物和安全策略等数据类型。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SandboxResult(BaseModel):
    """沙箱执行结果。

    Attributes:
        success: 是否执行成功（验证通过且无运行时错误）
        output: 标准输出内容
        error: 错误信息（验证失败或执行异常时非空）
        executed_at: 执行时间
        started_at: 开始时间（用于计算耗时）
        finished_at: 结束时间（用于计算耗时）
        duration_ms: 执行耗时（毫秒），计算属性

    Example:
        >>> result = SandboxResult(success=True, output="hello")
        >>> result.success
        True
    """

    success: bool
    output: str = ""
    error: Optional[str] = None
    executed_at: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    @property
    def duration_ms(self) -> float:
        """执行耗时（毫秒）。

        Returns:
            若 started_at / finished_at 均存在，返回实际耗时；否则返回 0.0。
        """
        if self.started_at is not None and self.finished_at is not None:
            delta = self.finished_at - self.started_at
            return delta.total_seconds() * 1000.0
        return 0.0


class CodeArtifact(BaseModel):
    """待验证的代码产物。

    Attributes:
        code: Python 代码字符串
        artifact_type: 产物类型，可选值：agent_def / tool_def / workflow_def / python_snippet
        description: 可选的描述信息

    Example:
        >>> artifact = CodeArtifact(code="x = 1 + 2", artifact_type="python_snippet")
        >>> artifact.artifact_type
        'python_snippet'
    """

    code: str
    artifact_type: str = Field(
        default="python_snippet",
        description="产物类型：agent_def / tool_def / workflow_def / python_snippet",
    )
    description: Optional[str] = None


class SandboxPolicy(BaseModel):
    """沙箱安全策略。

    Attributes:
        allowed_imports: 白名单模块列表，只有这些模块可以被 import
        max_execution_ms: 最大执行时间（毫秒），默认 5000ms
        allow_network: 是否允许网络操作，默认 False
        allow_file_io: 是否允许文件 I/O 操作，默认 False

    Example:
        >>> policy = SandboxPolicy(allowed_imports=["json", "re"])
        >>> policy.allow_network
        False
    """

    allowed_imports: list[str] = Field(
        default_factory=lambda: ["json", "re", "datetime", "math", "random"],
        description="允许 import 的模块白名单",
    )
    max_execution_ms: int = Field(default=5000, description="最大执行时间（毫秒）")
    allow_network: bool = Field(default=False, description="是否允许网络操作")
    allow_file_io: bool = Field(default=False, description="是否允许文件 I/O 操作")
