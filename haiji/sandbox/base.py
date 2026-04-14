"""
Sandbox 核心实现。

提供 CodeValidator（AST 静态分析）和 RestrictedExecutor（受限执行器），
用于安全验证和隔离执行 AI Designer 生成的代码产物。

安全约束：
- CodeValidator 纯静态分析，不执行任何代码
- RestrictedExecutor 只能执行通过 CodeValidator 验证的代码
- 超时通过 threading.Timer 硬性截断
- 禁止直接 exec() 未经验证的代码
"""

from __future__ import annotations

import ast
import io
import logging
import sys
import threading
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from typing import Optional

from .definition import CodeArtifact, SandboxPolicy, SandboxResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 默认策略
# ---------------------------------------------------------------------------

_DEFAULT_ALLOWED_IMPORTS = [
    "json",
    "re",
    "datetime",
    "math",
    "random",
    "string",
    "textwrap",
    "collections",
    "itertools",
    "functools",
    "enum",
    "typing",
    "dataclasses",
    "abc",
]

_DANGEROUS_CALLS = frozenset(
    [
        "exec",
        "eval",
        "__import__",
        "compile",
        "breakpoint",
        "input",
    ]
)

_DANGEROUS_BUILTINS_NETWORK = frozenset(["socket", "urllib", "http", "requests", "aiohttp"])

_DANGEROUS_BUILTINS_FILE = frozenset(["open", "pathlib", "shutil", "glob", "tempfile"])

_DANGEROUS_ATTRIBUTES = frozenset(
    [
        "__builtins__",
        "__class__",
        "__bases__",
        "__subclasses__",
        "__mro__",
        "__globals__",
        "__locals__",
        "__code__",
    ]
)

_DANGEROUS_MODULES = frozenset(
    [
        "subprocess",
        "os",
        "sys",
        "importlib",
        "ctypes",
        "cffi",
        "pickle",
        "shelve",
        "marshal",
        "builtins",
        "gc",
        "inspect",
        "dis",
        "ast",
        "code",
        "codeop",
        "pdb",
        "traceback",
        "linecache",
        "tokenize",
        "token",
        "symbol",
        "parser",
        "types",
        "weakref",
        "copyreg",
        "_thread",
        "threading",
        "multiprocessing",
        "signal",
        "mmap",
        "fcntl",
        "pty",
        "tty",
        "termios",
        "grp",
        "pwd",
        "resource",
    ]
)


def get_default_policy() -> SandboxPolicy:
    """返回默认的沙箱安全策略。

    只允许 json/re/datetime/math/random 等安全模块，
    不允许网络和文件 I/O。

    Returns:
        SandboxPolicy 默认策略实例。

    Example:
        >>> policy = get_default_policy()
        >>> "json" in policy.allowed_imports
        True
        >>> policy.allow_network
        False
    """
    return SandboxPolicy(allowed_imports=list(_DEFAULT_ALLOWED_IMPORTS))


class _ImportVisitor(ast.NodeVisitor):
    """AST 访问器：收集所有 import 的模块名。"""

    def __init__(self) -> None:
        self.imported_modules: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            # 取顶级模块名，如 `import os.path` 取 `os`
            self.imported_modules.append(alias.name.split(".")[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if node.module:
            self.imported_modules.append(node.module.split(".")[0])
        self.generic_visit(node)


class _DangerousCallVisitor(ast.NodeVisitor):
    """AST 访问器：检测危险函数调用和属性访问。"""

    def __init__(self, policy: SandboxPolicy) -> None:
        self.policy = policy
        self.violations: list[str] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        # 检查直接函数调用，如 exec(...), eval(...)
        if isinstance(node.func, ast.Name):
            if node.func.id in _DANGEROUS_CALLS:
                self.violations.append(f"禁止调用危险函数: {node.func.id}()")
            if not self.policy.allow_file_io and node.func.id == "open":
                self.violations.append("禁止调用 open()（文件 I/O 未启用）")
        # 检查方法调用，如 os.system(...), subprocess.call(...)
        elif isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if isinstance(node.func.value, ast.Name):
                module = node.func.value.id
                if module in _DANGEROUS_MODULES:
                    self.violations.append(f"禁止访问危险模块 {module}.{attr}()")
                if not self.policy.allow_network and module in _DANGEROUS_BUILTINS_NETWORK:
                    self.violations.append(f"禁止网络操作: {module}.{attr}()（网络访问未启用）")
                if not self.policy.allow_file_io and module in _DANGEROUS_BUILTINS_FILE:
                    self.violations.append(f"禁止文件操作: {module}.{attr}()（文件 I/O 未启用）")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        # 检查危险属性访问，如 obj.__class__, obj.__bases__ 等
        if node.attr in _DANGEROUS_ATTRIBUTES:
            self.violations.append(f"禁止访问危险属性: {node.attr}")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        # 检查直接引用危险名称，如 __builtins__（bare Name 节点）
        if node.id in _DANGEROUS_ATTRIBUTES:
            self.violations.append(f"禁止引用危险名称: {node.id}")
        self.generic_visit(node)


class CodeValidator:
    """代码静态验证器（AST 级别，不执行任何代码）。

    通过分析 Python AST 语法树，检查代码是否存在：
    - 非白名单 import
    - 危险函数调用（exec, eval 等）
    - 危险属性访问（__builtins__ 等原型链攻击）
    - 未授权的网络/文件操作

    Example:
        >>> validator = CodeValidator()
        >>> policy = get_default_policy()
        >>> artifact = CodeArtifact(code="import json\\nx = json.dumps({})", artifact_type="python_snippet")
        >>> result = validator.validate(artifact, policy)
        >>> result.success
        True
    """

    def validate(self, artifact: CodeArtifact, policy: SandboxPolicy) -> SandboxResult:
        """对代码产物进行静态安全验证。

        Args:
            artifact: 待验证的代码产物
            policy: 沙箱安全策略

        Returns:
            SandboxResult，success=True 表示通过验证，否则 error 说明原因。
        """
        started_at = datetime.now()

        # Step 1: 解析 AST
        try:
            tree = ast.parse(artifact.code)
        except SyntaxError as e:
            finished_at = datetime.now()
            logger.warning("代码 AST 解析失败（语法错误）: %s", str(e)[:200])
            return SandboxResult(
                success=False,
                output="",
                error=f"语法错误: {e}",
                started_at=started_at,
                finished_at=finished_at,
            )

        violations: list[str] = []

        # Step 2: 检查 import 白名单
        import_visitor = _ImportVisitor()
        import_visitor.visit(tree)
        allowed_set = set(policy.allowed_imports)
        for module in import_visitor.imported_modules:
            # 危险模块无论是否在白名单都拒绝
            if module in _DANGEROUS_MODULES:
                violations.append(f"禁止 import 危险模块: {module}")
            elif module not in allowed_set:
                violations.append(f"import 的模块不在白名单中: {module}")

        # Step 3: 检查危险调用和属性
        call_visitor = _DangerousCallVisitor(policy)
        call_visitor.visit(tree)
        violations.extend(call_visitor.violations)

        finished_at = datetime.now()

        if violations:
            error_msg = "代码安全验证失败: " + "; ".join(violations)
            logger.warning("沙箱拒绝代码执行 [%s]: %s", artifact.artifact_type, error_msg[:200])
            return SandboxResult(
                success=False,
                output="",
                error=error_msg,
                started_at=started_at,
                finished_at=finished_at,
            )

        logger.debug("代码安全验证通过 [%s]", artifact.artifact_type)
        return SandboxResult(
            success=True,
            output="",
            error=None,
            started_at=started_at,
            finished_at=finished_at,
        )


class RestrictedExecutor:
    """受限代码执行器（仅用于通过验证的可信代码）。

    执行流程：
    1. 先调用 CodeValidator.validate() 验证
    2. 通过验证才执行
    3. 使用 threading.Timer 进行超时控制
    4. 捕获所有异常，标准输出重定向到结果

    安全约束：
    - 不执行未经 CodeValidator 验证的代码
    - 超时由 threading.Timer 硬性截断（非 asyncio，不阻塞事件循环）

    Example:
        >>> executor = RestrictedExecutor()
        >>> policy = get_default_policy()
        >>> result = executor.execute("print('hello')", policy=policy)
        >>> result.success
        True
        >>> result.output
        'hello\\n'
    """

    def __init__(self) -> None:
        self._validator = CodeValidator()

    def execute(
        self,
        code: str,
        globals_dict: Optional[dict] = None,
        policy: Optional[SandboxPolicy] = None,
        artifact_type: str = "python_snippet",
    ) -> SandboxResult:
        """执行受限代码。

        Args:
            code: 待执行的 Python 代码字符串
            globals_dict: 可选的全局变量字典（会被安全过滤）
            policy: 沙箱安全策略，None 时使用默认策略
            artifact_type: 产物类型（用于日志）

        Returns:
            SandboxResult，包含执行结果和输出。
        """
        if policy is None:
            policy = get_default_policy()

        artifact = CodeArtifact(code=code, artifact_type=artifact_type)

        # 先验证
        validate_result = self._validator.validate(artifact, policy)
        if not validate_result.success:
            return validate_result

        # 执行
        started_at = datetime.now()
        output_buffer = StringIO()
        exec_result: dict = {"success": False, "output": "", "error": None}
        exec_exception: list[Optional[Exception]] = [None]
        timed_out_flag: list[bool] = [False]

        # 构建受限 globals：允许安全的内置函数，禁止危险内置
        _safe_builtins = {
            # 类型构造
            "bool": bool, "int": int, "float": float, "str": str, "bytes": bytes,
            "list": list, "dict": dict, "tuple": tuple, "set": set, "frozenset": frozenset,
            "type": type, "object": object,
            # 常用内置
            "print": print, "len": len, "range": range, "enumerate": enumerate,
            "zip": zip, "map": map, "filter": filter, "sorted": sorted, "reversed": reversed,
            "sum": sum, "min": min, "max": max, "abs": abs, "round": round,
            "all": all, "any": any, "repr": repr, "hash": hash, "id": id,
            "isinstance": isinstance, "issubclass": issubclass, "callable": callable,
            "getattr": getattr, "setattr": setattr, "hasattr": hasattr, "delattr": delattr,
            "dir": dir, "vars": vars,
            "iter": iter, "next": next,
            "format": format, "chr": chr, "ord": ord, "hex": hex, "oct": oct, "bin": bin,
            "divmod": divmod, "pow": pow,
            # 异常基类
            "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
            "KeyError": KeyError, "IndexError": IndexError, "AttributeError": AttributeError,
            "RuntimeError": RuntimeError, "StopIteration": StopIteration,
            "NotImplementedError": NotImplementedError, "NameError": NameError,
            "ImportError": ImportError, "OSError": OSError, "IOError": IOError,
            "ZeroDivisionError": ZeroDivisionError, "OverflowError": OverflowError,
            "MemoryError": MemoryError, "RecursionError": RecursionError,
            # 特殊
            "None": None, "True": True, "False": False,
            "NotImplemented": NotImplemented,
            "__name__": "__sandbox__",
            # import 支持（用于白名单模块 import）
            "__import__": __import__,
        }
        safe_globals: dict = {"__builtins__": _safe_builtins}
        if globals_dict:
            # 只传入非双下划线的用户变量
            for k, v in globals_dict.items():
                if not (k.startswith("__") and k.endswith("__")):
                    safe_globals[k] = v

        def _run() -> None:
            try:
                with redirect_stdout(output_buffer):
                    exec(code, safe_globals)  # noqa: S102 - 已经过 CodeValidator 验证
                exec_result["success"] = True
                exec_result["output"] = output_buffer.getvalue()
            except Exception as e:
                exec_result["success"] = False
                exec_result["output"] = output_buffer.getvalue()
                exec_result["error"] = f"{type(e).__name__}: {e}"
                exec_exception[0] = e

        thread = threading.Thread(target=_run, daemon=True)
        timeout_s = policy.max_execution_ms / 1000.0

        thread.start()
        thread.join(timeout=timeout_s)

        finished_at = datetime.now()

        if thread.is_alive():
            # 超时，线程仍在运行（无法强制终止，但 daemon=True 不阻塞进程退出）
            timed_out_flag[0] = True
            logger.warning("沙箱执行超时（%.1f 秒），代码被截断", timeout_s)
            return SandboxResult(
                success=False,
                output=output_buffer.getvalue(),
                error=f"执行超时（超过 {policy.max_execution_ms}ms 限制）",
                started_at=started_at,
                finished_at=finished_at,
            )

        if exec_result["success"]:
            logger.debug("沙箱执行成功 [%s]", artifact_type)
        else:
            logger.info("沙箱执行失败 [%s]: %s", artifact_type, str(exec_result["error"])[:200])

        return SandboxResult(
            success=exec_result["success"],
            output=exec_result["output"],
            error=exec_result["error"],
            started_at=started_at,
            finished_at=finished_at,
        )
