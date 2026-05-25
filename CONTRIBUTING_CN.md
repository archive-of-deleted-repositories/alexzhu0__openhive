# 贡献指南（中文）

感谢你向 OpenHive 贡献代码。请按以下流程提交，避免影响公共仓库的稳定性。

## 1. 开发环境

```bash
python -m pip install -e ".[dev]"
```

要求：

- Python 3.10+
- 已安装 `openhive` 命令（建议先执行 `python3 -m pip install -e .`）
- 不要提交真实 API Key、`.openhive_memory_*.json` 或本地临时文件

## 2. 代码规范

- 4 空格缩进，保持项目现有风格。
- 优先显式类型注解和清晰命名。
- 复杂逻辑添加必要注释，优先可读性。
- 参考 `pyproject.toml` 中的 `ruff` 配置。
- 小步提交，避免大面积猜测式重构。

## 3. Commit 规范

- 使用命令式前缀：`feat:` / `fix:` / `refactor:` / `test:`
- 一个 PR 只包含一个核心目标。
- 示例：
  - `feat: add runtime bridge routing test`
  - `fix: guard low-confidence retry fallback`
  - `test: add enterprise audit unit cases`

## 4. 必跑检查

```bash
python3 -m compileall -q src tests
python3 -m unittest discover -s tests/unit -p 'test_*.py'
openhive --help
```

有功能改动请补充对应测试，并在 PR 描述中贴上测试命令和输出。

## 5. PR 必填清单

每个 PR 需要说明：

- 修改目标与影响范围（1–3 句）
- 主要变更文件
- 配置变更说明（有则填写）
- 风险评估（高/中/低）
- 检查命令与结果

## 6. 变更讨论与兼容性

- 尽量先在 Issue 里复现问题再提 PR。
- 有兼容性影响请在 PR 标题/描述中标注 `BREAKING CHANGE`。
- 触及 OpenClaw / Hermes 外部 runtime 时，务必同步校验 `enterprise.runtime_bridge` 配置与文档。
