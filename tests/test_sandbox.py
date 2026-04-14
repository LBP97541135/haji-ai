"""
测试 haiji.sandbox 模块。

覆盖：
- SandboxResult.duration_ms 计算属性
- CodeArtifact / SandboxPolicy 数据结构
- get_default_policy 默认策略
- CodeValidator: import 白名单、黑名单 import 拒绝、危险调用拒绝、语法错误
- RestrictedExecutor: 正常执行、执行失败、超时截断、未验证代码拒绝
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Optional

import pytest

from haiji.sandbox import (
    CodeArtifact,
    CodeValidator,
    RestrictedExecutor,
    SandboxPolicy,
    SandboxResult,
    get_default_policy,
)


# ---------------------------------------------------------------------------
# SandboxResult
# ---------------------------------------------------------------------------


class TestSandboxResult:
    def test_duration_ms_with_start_and_finish(self):
        """有 started_at/finished_at 时正确计算耗时。"""
        start = datetime(2026, 1, 1, 0, 0, 0)
        end = datetime(2026, 1, 1, 0, 0, 1)  # 1 秒后
        result = SandboxResult(success=True, started_at=start, finished_at=end)
        assert abs(result.duration_ms - 1000.0) < 1.0

    def test_duration_ms_without_timestamps(self):
        """没有时间戳时 duration_ms 返回 0.0。"""
        result = SandboxResult(success=True)
        assert result.duration_ms == 0.0

    def test_duration_ms_without_started_at(self):
        """只有 finished_at 时 duration_ms 返回 0.0。"""
        result = SandboxResult(success=True, finished_at=datetime.now())
        assert result.duration_ms == 0.0

    def test_success_false_with_error(self):
        """失败结果包含错误信息。"""
        result = SandboxResult(success=False, error="语法错误: ...")
        assert not result.success
        assert result.error is not None

    def test_default_executed_at(self):
        """executed_at 有默认值。"""
        result = SandboxResult(success=True)
        assert result.executed_at is not None


# ---------------------------------------------------------------------------
# CodeArtifact
# ---------------------------------------------------------------------------


class TestCodeArtifact:
    def test_default_artifact_type(self):
        """默认 artifact_type 为 python_snippet。"""
        artifact = CodeArtifact(code="x = 1")
        assert artifact.artifact_type == "python_snippet"

    def test_custom_artifact_type(self):
        """可自定义 artifact_type。"""
        artifact = CodeArtifact(code="x = 1", artifact_type="agent_def")
        assert artifact.artifact_type == "agent_def"

    def test_optional_description(self):
        """description 默认为 None，可传入字符串。"""
        artifact = CodeArtifact(code="x = 1")
        assert artifact.description is None

        artifact2 = CodeArtifact(code="x = 1", description="测试代码")
        assert artifact2.description == "测试代码"


# ---------------------------------------------------------------------------
# SandboxPolicy
# ---------------------------------------------------------------------------


class TestSandboxPolicy:
    def test_default_policy_values(self):
        """默认策略：不允许网络和文件 I/O，超时 5000ms。"""
        policy = SandboxPolicy()
        assert not policy.allow_network
        assert not policy.allow_file_io
        assert policy.max_execution_ms == 5000

    def test_custom_policy(self):
        """可自定义策略。"""
        policy = SandboxPolicy(
            allowed_imports=["json", "re"],
            max_execution_ms=2000,
            allow_network=True,
        )
        assert policy.allow_network
        assert policy.max_execution_ms == 2000
        assert "json" in policy.allowed_imports


# ---------------------------------------------------------------------------
# get_default_policy
# ---------------------------------------------------------------------------


class TestGetDefaultPolicy:
    def test_returns_sandbox_policy(self):
        """get_default_policy 返回 SandboxPolicy 实例。"""
        policy = get_default_policy()
        assert isinstance(policy, SandboxPolicy)

    def test_json_in_allowed_imports(self):
        """json 在默认白名单中。"""
        policy = get_default_policy()
        assert "json" in policy.allowed_imports

    def test_re_in_allowed_imports(self):
        """re 在默认白名单中。"""
        policy = get_default_policy()
        assert "re" in policy.allowed_imports

    def test_no_network_by_default(self):
        """默认不允许网络。"""
        policy = get_default_policy()
        assert not policy.allow_network

    def test_no_file_io_by_default(self):
        """默认不允许文件 I/O。"""
        policy = get_default_policy()
        assert not policy.allow_file_io


# ---------------------------------------------------------------------------
# CodeValidator
# ---------------------------------------------------------------------------


class TestCodeValidatorImports:
    def setup_method(self):
        self.validator = CodeValidator()
        self.policy = get_default_policy()

    def test_allowed_import_passes(self):
        """白名单 import 通过验证。"""
        artifact = CodeArtifact(code="import json\nx = json.dumps({})")
        result = self.validator.validate(artifact, self.policy)
        assert result.success, result.error

    def test_allowed_import_from_passes(self):
        """from ... import ... 白名单通过。"""
        artifact = CodeArtifact(code="from json import dumps\nx = dumps({})")
        result = self.validator.validate(artifact, self.policy)
        assert result.success, result.error

    def test_re_import_passes(self):
        """re 白名单 import 通过。"""
        artifact = CodeArtifact(code="import re\npattern = re.compile(r'\\d+')")
        result = self.validator.validate(artifact, self.policy)
        assert result.success, result.error

    def test_unlisted_import_rejected(self):
        """不在白名单中的 import 被拒绝。"""
        artifact = CodeArtifact(code="import hashlib")
        result = self.validator.validate(artifact, self.policy)
        assert not result.success
        assert "hashlib" in result.error

    def test_os_import_rejected(self):
        """import os 被拒绝（危险模块）。"""
        artifact = CodeArtifact(code="import os")
        result = self.validator.validate(artifact, self.policy)
        assert not result.success
        assert "os" in result.error

    def test_sys_import_rejected(self):
        """import sys 被拒绝（危险模块）。"""
        artifact = CodeArtifact(code="import sys")
        result = self.validator.validate(artifact, self.policy)
        assert not result.success
        assert "sys" in result.error

    def test_subprocess_import_rejected(self):
        """import subprocess 被拒绝（危险模块）。"""
        artifact = CodeArtifact(code="import subprocess")
        result = self.validator.validate(artifact, self.policy)
        assert not result.success
        assert "subprocess" in result.error

    def test_os_submodule_import_rejected(self):
        """from os import path 被拒绝（os 是危险模块）。"""
        artifact = CodeArtifact(code="from os import path")
        result = self.validator.validate(artifact, self.policy)
        assert not result.success

    def test_no_import_passes(self):
        """没有 import 的纯计算代码通过。"""
        artifact = CodeArtifact(code="x = 1 + 2\ny = x * 3")
        result = self.validator.validate(artifact, self.policy)
        assert result.success, result.error


class TestCodeValidatorDangerousCalls:
    def setup_method(self):
        self.validator = CodeValidator()
        self.policy = get_default_policy()

    def test_exec_call_rejected(self):
        """exec() 调用被拒绝。"""
        artifact = CodeArtifact(code="exec('print(1)')")
        result = self.validator.validate(artifact, self.policy)
        assert not result.success
        assert "exec" in result.error

    def test_eval_call_rejected(self):
        """eval() 调用被拒绝。"""
        artifact = CodeArtifact(code="x = eval('1 + 2')")
        result = self.validator.validate(artifact, self.policy)
        assert not result.success
        assert "eval" in result.error

    def test_dunder_import_call_rejected(self):
        """__import__() 调用被拒绝。"""
        artifact = CodeArtifact(code="m = __import__('os')")
        result = self.validator.validate(artifact, self.policy)
        assert not result.success

    def test_open_call_rejected_when_file_io_disabled(self):
        """allow_file_io=False 时 open() 被拒绝。"""
        artifact = CodeArtifact(code="f = open('test.txt')")
        result = self.validator.validate(artifact, self.policy)
        assert not result.success
        assert "open" in result.error.lower()

    def test_open_call_allowed_when_file_io_enabled(self):
        """allow_file_io=True 时 open() 不被危险调用检查阻止（但可能被 import 规则阻止）。"""
        policy = SandboxPolicy(allow_file_io=True)
        artifact = CodeArtifact(code="x = 1  # open() 未调用")
        result = self.validator.validate(artifact, policy)
        assert result.success

    def test_compile_call_rejected(self):
        """compile() 调用被拒绝。"""
        artifact = CodeArtifact(code="c = compile('x=1', '<str>', 'exec')")
        result = self.validator.validate(artifact, self.policy)
        assert not result.success

    def test_os_system_via_attribute_rejected(self):
        """os.system() 属性调用被拒绝（os 是危险模块）。"""
        # import os 已被拒绝，但即使有 os 变量，os.system 属性访问也被拒绝
        artifact = CodeArtifact(code="import os\nos.system('ls')")
        result = self.validator.validate(artifact, self.policy)
        assert not result.success


class TestCodeValidatorDangerousAttributes:
    def setup_method(self):
        self.validator = CodeValidator()
        self.policy = get_default_policy()

    def test_builtins_attribute_rejected(self):
        """访问 __builtins__ 被拒绝。"""
        artifact = CodeArtifact(code="b = __builtins__")
        result = self.validator.validate(artifact, self.policy)
        assert not result.success
        assert "__builtins__" in result.error

    def test_class_attribute_rejected(self):
        """访问 __class__ 属性被拒绝。"""
        artifact = CodeArtifact(code="x = (1).__class__")
        result = self.validator.validate(artifact, self.policy)
        assert not result.success

    def test_subclasses_attribute_rejected(self):
        """访问 __subclasses__ 属性被拒绝（原型链攻击）。"""
        artifact = CodeArtifact(code="x = object.__subclasses__()")
        result = self.validator.validate(artifact, self.policy)
        assert not result.success


class TestCodeValidatorSyntaxError:
    def setup_method(self):
        self.validator = CodeValidator()
        self.policy = get_default_policy()

    def test_syntax_error_returns_failure(self):
        """语法错误返回 success=False，error 包含语法错误信息。"""
        artifact = CodeArtifact(code="def foo(:\n    pass")
        result = self.validator.validate(artifact, self.policy)
        assert not result.success
        assert "语法错误" in result.error or "SyntaxError" in result.error

    def test_empty_code_passes(self):
        """空代码通过验证（没有 import，没有危险调用）。"""
        artifact = CodeArtifact(code="")
        result = self.validator.validate(artifact, self.policy)
        assert result.success

    def test_comment_only_passes(self):
        """只有注释的代码通过验证。"""
        artifact = CodeArtifact(code="# 这只是一个注释")
        result = self.validator.validate(artifact, self.policy)
        assert result.success

    def test_validate_result_has_timestamps(self):
        """验证结果包含时间戳。"""
        artifact = CodeArtifact(code="x = 1")
        result = self.validator.validate(artifact, self.policy)
        assert result.started_at is not None
        assert result.finished_at is not None
        assert result.finished_at >= result.started_at

    def test_validate_duration_ms_positive(self):
        """验证耗时为非负数。"""
        artifact = CodeArtifact(code="x = 1 + 2")
        result = self.validator.validate(artifact, self.policy)
        assert result.duration_ms >= 0.0


# ---------------------------------------------------------------------------
# RestrictedExecutor
# ---------------------------------------------------------------------------


class TestRestrictedExecutorNormal:
    def setup_method(self):
        self.executor = RestrictedExecutor()
        self.policy = get_default_policy()

    def test_execute_print(self):
        """执行 print() 并捕获输出。"""
        result = self.executor.execute("print('hello, sandbox!')", policy=self.policy)
        assert result.success, result.error
        assert "hello, sandbox!" in result.output

    def test_execute_arithmetic(self):
        """执行算术运算。"""
        result = self.executor.execute("x = 1 + 2\nprint(x)", policy=self.policy)
        assert result.success
        assert "3" in result.output

    def test_execute_with_allowed_import(self):
        """执行包含白名单 import 的代码。"""
        result = self.executor.execute(
            "import json\nprint(json.dumps({'k': 'v'}))",
            policy=self.policy,
        )
        assert result.success
        assert "k" in result.output

    def test_execute_multiple_prints(self):
        """多行输出被正确捕获。"""
        code = "print('line1')\nprint('line2')\nprint('line3')"
        result = self.executor.execute(code, policy=self.policy)
        assert result.success
        assert "line1" in result.output
        assert "line2" in result.output
        assert "line3" in result.output

    def test_execute_result_has_timestamps(self):
        """执行结果包含时间戳。"""
        result = self.executor.execute("x = 1", policy=self.policy)
        assert result.started_at is not None
        assert result.finished_at is not None

    def test_execute_duration_ms_positive(self):
        """执行耗时为正数。"""
        result = self.executor.execute("x = 1 + 2", policy=self.policy)
        assert result.duration_ms >= 0.0

    def test_execute_with_globals_dict(self):
        """可通过 globals_dict 传入变量。"""
        result = self.executor.execute(
            "print(my_var * 2)",
            globals_dict={"my_var": 21},
            policy=self.policy,
        )
        assert result.success
        assert "42" in result.output

    def test_execute_runtime_error(self):
        """运行时错误返回 success=False，error 包含异常信息。"""
        result = self.executor.execute("x = 1 / 0", policy=self.policy)
        assert not result.success
        assert result.error is not None
        assert "ZeroDivisionError" in result.error

    def test_execute_name_error(self):
        """引用未定义变量时 NameError 被捕获。"""
        result = self.executor.execute("print(undefined_variable)", policy=self.policy)
        assert not result.success
        assert "NameError" in result.error

    def test_execute_default_policy_when_none(self):
        """policy=None 时使用默认策略。"""
        result = self.executor.execute("print('ok')", policy=None)
        assert result.success


class TestRestrictedExecutorValidationReject:
    def setup_method(self):
        self.executor = RestrictedExecutor()
        self.policy = get_default_policy()

    def test_reject_exec_call(self):
        """exec() 调用被 validator 拒绝，不执行。"""
        result = self.executor.execute("exec('print(1)')", policy=self.policy)
        assert not result.success
        assert "exec" in result.error

    def test_reject_eval_call(self):
        """eval() 调用被 validator 拒绝，不执行。"""
        result = self.executor.execute("x = eval('1 + 2')", policy=self.policy)
        assert not result.success
        assert "eval" in result.error

    def test_reject_blacklist_import(self):
        """黑名单 import 被 validator 拒绝，不执行。"""
        result = self.executor.execute("import os\nprint(os.getcwd())", policy=self.policy)
        assert not result.success
        assert "os" in result.error

    def test_reject_syntax_error(self):
        """语法错误被 validator 拒绝，不执行。"""
        result = self.executor.execute("def f(:\n    pass", policy=self.policy)
        assert not result.success


class TestRestrictedExecutorTimeout:
    def setup_method(self):
        self.executor = RestrictedExecutor()

    def test_timeout_kills_infinite_loop(self):
        """无限循环在超时后被截断。"""
        policy = SandboxPolicy(max_execution_ms=200)  # 200ms 超时
        code = "while True:\n    pass"
        start = time.monotonic()
        result = self.executor.execute(code, policy=policy)
        elapsed = time.monotonic() - start

        assert not result.success
        assert "超时" in result.error or "timeout" in result.error.lower()
        # 执行时间应该接近超时时间（允许一定误差）
        assert elapsed < 3.0, f"超时截断太慢，实际等待了 {elapsed:.2f}s"

    def test_fast_code_not_timed_out(self):
        """快速代码不会被超时。"""
        policy = SandboxPolicy(max_execution_ms=1000)
        result = self.executor.execute("x = 1 + 2\nprint(x)", policy=policy)
        assert result.success


# ---------------------------------------------------------------------------
# 集成：validator + executor 协同
# ---------------------------------------------------------------------------


class TestSandboxIntegration:
    def setup_method(self):
        self.validator = CodeValidator()
        self.executor = RestrictedExecutor()
        self.policy = get_default_policy()

    def test_validate_then_execute_safe_code(self):
        """先 validate 通过，再 execute 成功。"""
        code = "import json\ndata = json.dumps({'result': 42})\nprint(data)"
        artifact = CodeArtifact(code=code, artifact_type="python_snippet")

        # 验证通过
        validate_result = self.validator.validate(artifact, self.policy)
        assert validate_result.success

        # 执行成功
        exec_result = self.executor.execute(code, policy=self.policy)
        assert exec_result.success
        assert "42" in exec_result.output

    def test_validate_reject_unsafe_code(self):
        """unsafe 代码 validate 失败，executor 也应拒绝。"""
        code = "import subprocess\nsubprocess.run(['ls'])"
        artifact = CodeArtifact(code=code)

        validate_result = self.validator.validate(artifact, self.policy)
        assert not validate_result.success

        exec_result = self.executor.execute(code, policy=self.policy)
        assert not exec_result.success

    def test_multiple_artifacts_independent(self):
        """多个 artifact 互相独立，一个失败不影响另一个。"""
        safe_code = "print('safe')"
        unsafe_code = "exec('x = 1')"

        safe_result = self.executor.execute(safe_code, policy=self.policy)
        unsafe_result = self.executor.execute(unsafe_code, policy=self.policy)

        assert safe_result.success
        assert not unsafe_result.success
