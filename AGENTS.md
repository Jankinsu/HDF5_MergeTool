# 项目规范

## Python 与依赖管理

- 本项目统一使用 `uv` 管理 Python 版本、虚拟环境和依赖。
- 默认 Python 版本为 3.12；开发前应使用 `uv python pin 3.12` 确保本地版本一致。
- 项目依赖以 `pyproject.toml` 和 `uv.lock` 为唯一事实来源，不再维护 `requirements.txt`。
- 安装或同步依赖使用 `uv sync`，运行项目或测试优先使用 `uv run`。

## 版本管理

- 当前项目版本为 `0.1.0`，以 `pyproject.toml` 中的 `project.version` 为准。
- Git tag 使用 `v<version>` 格式；当前版本对应 tag 为 `v0.1.0`。
- 发布或升级版本时，必须同步修改 `pyproject.toml` 与 Git tag，二者的版本号必须一致。

## 项目结构

- 应优先采用 `src/`、`tests/` 等规范目录；当前项目暂保持现有脚本和测试文件布局，避免无关重构。
- 大型本地 HDF5 输入文件和生成文件不纳入 Git 版本控制。

## 验证

- 依赖同步：`uv sync`
- 测试：`uv run python -m unittest -v`
- 版本核对：`uv run python -c "import importlib.metadata; print(importlib.metadata.version('hdf5-merge'))"`，并与 `git tag` 核对。
