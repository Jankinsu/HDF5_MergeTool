# HDF5 文件合并工具

本项目提供一个基于 Python、h5py 和 uv 的 HDF5 文件合并命令行工具。当前工具面向两份同类型文件的合并，例如：

```text
182Vps.h5 + 352Vps.h5 -> merged_Vps.h5
182Hps.h5 + 352Hps.h5 -> merged_Hps.h5
```

工具合并 HDF5 的 Group/Dataset 路径树，不会把 Dataset 沿某个维度拼接，也不会修改输入文件。

## 安装和运行

项目使用 uv 管理 Python、虚拟环境和依赖：

```text
uv python pin 3.12
uv sync
```

合并 Vps 文件：

```text
uv run hdf5-merge 182Vps.h5 352Vps.h5 --output merged_Vps.h5
```

合并 Hps 文件：

```text
uv run hdf5-merge 182Hps.h5 352Hps.h5 --output merged_Hps.h5
```

也可以使用模块脚本形式：

```text
uv run python hdf5_merge.py 182Vps.h5 352Vps.h5
```

查看版本和帮助：

```text
uv run hdf5-merge --version
uv run hdf5-merge --help
```

默认输出文件名根据输入类型推断：Vps 使用 `merged_Vps.h5`，Hps 使用 `merged_Hps.h5`。也可以用 `--output` 指定路径。

## 合并范围和边界

当前文件的根结构主要是：

```text
/
├── backward_scattering_data/
│   └── theta_<theta>_phi_<phi>/
└── forward_scattering_data/
    └── theta_<theta>_phi_<phi>/
        └── segments/scNo*/contourNo*
```

根 Group `/backward_scattering_data` 和 `/forward_scattering_data` 是合并容器，会递归处理其中的场景 Group。

场景 Group 是例如：

```text
/backward_scattering_data/theta_10.0_phi_182.0
```

合并规则如下：

1. 不同名场景 Group 会完整复制到输出文件。
2. 同名场景 Group 以第一个输入文件为准，第二个输入文件中的整个同名 Group 跳过。
3. 因此，第二个文件同名 Group 中新增的 Dataset 或子 Group 也不会补入输出。
4. 根 Group 的属性保留第一个输入文件的属性；新复制的场景会保留自己的属性、Dataset 类型、chunk 和压缩设置。
5. 只有同一路径的 Dataset 才需要类型和形状兼容检查。不同场景即使 Dataset 长度不同，也可以共存。

例如：

```text
文件 A: /data/sample/value = 1
文件 B: /data/sample/value = 2
```

如果 `/data/sample` 是场景 Group，合并后保留文件 A 的整个 `/data/sample`，结果中的 `value` 为 `1`。

注意：本工具不是数组拼接工具，不会把 `(325, 3, 2)` 和 `(340, 3, 2)` 自动拼成一个数组。

## 输入安全检查

执行正式复制前，工具会检查：

- 两个文件存在且可以打开；
- 文件名必须明确包含 `Vps` 或 `Hps`，且只能包含其中一种类型；
- 两个输入文件必须是同一种类型，禁止 `182Vps.h5 + 352Hps.h5`；
- 必需的根 Group 是否存在；
- 根 Group 下重叠路径的节点类型、Dataset 类型和形状是否兼容。

如果输出文件已经存在，工具默认拒绝覆盖：

```text
uv run hdf5-merge 182Vps.h5 352Vps.h5 --output merged_Vps.h5 --force
```

只有确认需要覆盖时才使用 `--force`。输出路径不能与任一输入路径相同。

## 进度和耗时

正式合并时，命令行会输出 ASCII 进度信息，避免大文件复制期间无法判断程序是否仍在运行：

```text
[progress] validating input files and compatibility..., elapsed 0.2s
[progress] copying 182Vps.h5: /backward_scattering_data 47% (160/336), elapsed 18.4s
[progress] temporary write complete; validating output..., elapsed 70.1s
[progress] output validation complete: merged_Vps.h5, elapsed 76.8s
[progress] completed in 76.8s
```

进度百分比按场景 Group 数量统计，不是按字节数统计。不同场景大小可能不同，因此百分比不能精确表示剩余时间；单个场景内部复制期间也可能暂时没有新的进度行。

## 只校验不合并

如果只想确认输入文件是否可以合并，不创建输出文件：

```text
uv run hdf5-merge 182Vps.h5 352Vps.h5 --validate-only
```

## 安全写出

输出先写入同目录临时文件，写入和结构校验成功后才替换为最终文件。过程中失败会清理临时文件，输入文件不会被修改。

## 测试

运行单元测试：

```text
uv run python -m unittest -v
```

测试覆盖：

- 不同场景的并集合并；
- 同名场景 Group 整体跳过；
- Vps/Hps 类型误配和未知类型文件名；
- 进度回调和耗时信息；
- `--validate-only` 不产生输出；
- 输出文件存在时必须使用 `--force`。

使用真实数据时，建议先执行 `--validate-only`，再进行正式合并。

## 项目文件

- `hdf5_merge.py`：核心实现和 CLI 入口；
- `test_hdf5_merge.py`：单元测试；
- `pyproject.toml`：项目元数据、依赖和命令行入口；
- `uv.lock`：锁定依赖版本；
- `*.h5`：本地输入和生成文件，不纳入 Git 版本控制。