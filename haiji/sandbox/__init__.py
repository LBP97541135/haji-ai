"""
haiji.sandbox - 沙箱模块

为 AI Designer 生成的代码/Agent 定义提供安全验证和隔离执行环境。

核心组件：
- CodeValidator: 纯 AST 静态分析器，不执行任何代码，检查 import 白名单和危险调用
- RestrictedExecutor: 受限执行器，只执行通过 CodeValidator 验证的代码，支持超时控制
- SandboxPolicy: 安全策略配置（import 白名单、超时、网络/文件权限）
- CodeArtifact: 待验证的代码产物
- SandboxResult: 执行结果（含 duration_ms 计算属性）
- get_default_policy: 获取默认安全策略

安全约束：
- 禁止直接 exec() 未经验证的代码
- CodeValidator 是纯静态分析（AST），不执行任何代码
- RestrictedExecutor 只能执行通过 CodeValidator 验证的代码
- 超时通过 threading.Timer 硬性截断

Example::

    from haiji.sandbox import CodeArtifact, CodeValidator, RestrictedExecutor, get_default_policy

    policy = get_default_policy()
    validator = CodeValidator()

    artifact = CodeArtifact(code="import json; x = json.dumps({'a': 1})", artifact_type="python_snippet")
    result = validator.validate(artifact, policy)
    print(result.success)  # True

    executor = RestrictedExecutor()
    result = executor.execute("print('hello, sandbox!')", policy=policy)
    print(result.output)  # hello, sandbox!
"""

from .base import CodeValidator, RestrictedExecutor, get_default_policy
from .definition import CodeArtifact, SandboxPolicy, SandboxResult

__all__ = [
    "CodeArtifact",
    "SandboxPolicy",
    "SandboxResult",
    "CodeValidator",
    "RestrictedExecutor",
    "get_default_policy",
]
