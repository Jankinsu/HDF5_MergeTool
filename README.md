# HDF5 文件合并工具

这是一个基于 Python 和 `h5py` 的 HDF5 文件合并工具。当前数据文件用于合并两批不同 `phi` 角度的散射数据：

```text
182Vps.h5 + 352Vps.h5 -> merged_Vps.h5
182Hps.h5 + 352Hps.h5 -> merged_Hps.h5
```

工具按 HDF5 的 Group/Dataset 路径合并，不会把两个文件中的数组沿某个轴拼接，也不会修改原始输入文件。

## 文件结构

当前文件的根节点包含两个 Group：

```text
/
├── backward_scattering_data/
│   └── theta_<theta>_phi_<phi>/
│       ├── bsc_alpha
│       ├── bsc_amp
│       ├── bsc_lens
│       ├── bsc_phi
│       └── bsc_pos
└── forward_scattering_data/
    └── theta_<theta>_phi_<phi>/
        ├── fsc_*
        └── segments/scNo*/contourNo*
```

例如，下面两个 Group 的路径不同，因此会同时保留：

```text
/backward_scattering_data/theta_10.0_phi_182.0
/backward_scattering_data/theta_10.0_phi_352.0
```

Group 内 Dataset 的长度可以不同。例如某个场景的 `bsc_amp` 可能是 `(325, 3, 2)`，另一个场景可能是 `(340, 3, 2)`。这类不同长度是正常的，因为它们属于不同场景，工具不会尝试把它们拼成一个数组。

## 合并边界和规则

### 1. 合并的基本单位是路径

工具合并的是 HDF5 路径树。例如：

```text
/forward_scattering_data/theta_10.0_phi_182.0/segments/scNo0/contourNo0
```

是一个完整路径。不存在于第一个文件中的 Group 或 Dataset，会从第二个文件复制到输出文件。

### 2. 同名 Group 的处理

同名 Group 不会进行 Dataset 级别的“拼接”。第一个输入文件中的整个 Group 优先，第二个文件中的同名 Group 整体跳过。

例如：

```text
文件 A: /data/sample/value = 1
文件 B: /data/sample/value = 2
```

合并后保留文件 A 的 `/data/sample`，结果为 `value = 1`。文件 B 中该 Group 内新增但文件 A 没有的内容也不会补入，因为 Group 的冲突策略是“整体跳过”。

当前实现中两个输入文件的共同根 Group（`backward_scattering_data` 和 `forward_scattering_data`）会递归处理；真正发生冲突的场景 Group 则按上述规则整体保留第一个来源。

### 3. 同名 Dataset 的处理

同一路径 Dataset 也保留第一个文件的数据和属性，第二个文件的同名 Dataset 跳过。

合并前会严格检查重叠 Dataset 的：

- 数据类型，例如 `float64` 与 `int32` 不兼容；
- 完整形状，例如 `(100, 3)` 与 `(120, 3)` 不兼容。

注意：形状不同的 Dataset 只有在路径也相同的情况下才会报错。不同场景路径下，即使长度不同，也可以正常共存。

### 4. 节点类型冲突会报错

如果同一路径在一个文件中是 Group、在另一个文件中是 Dataset，合并会在写出前失败。例如：

```text
文件 A: /data/sample        Group
文件 B: /data/sample        Dataset
```

这种情况不能安全地自动选择，因此不会生成最终输出文件。

### 5. 属性和存储信息

第一个来源的 root、Group 和 Dataset 属性优先保留。新复制的 Dataset 会尽量保留原有的数据类型、chunk、压缩和其他 HDF5 存储设置。

### 6. 不支持的操作

当前工具不执行以下操作：

- 沿 Dataset 的某个维度拼接数组；
- 根据 `theta` 或 `phi` 数值重新排序场景；
- 自动去重内容相同但路径不同的场景；
- 自动解决同名 Group 的内部差异；
- 覆盖原始输入文件。

## 安装依赖

推荐使用项目环境安装：

```text
uv pip install -r requirements.txt
```

也可以使用普通 Python 环境：

```text
python -m pip install -r requirements.txt
```

当前依赖为 `h5py`。

## 使用方法

合并 Vps 文件：

```text
python hdf5_merge.py 182Vps.h5 352Vps.h5 --output merged_Vps.h5
```

合并 Hps 文件：

```text
python hdf5_merge.py 182Hps.h5 352Hps.h5 --output merged_Hps.h5
```

如果不指定 `--output`，工具会根据输入文件名推断：

- 输入文件名包含 `Vps` 时，默认输出 `merged_Vps.h5`；
- 输入文件名包含 `Hps` 时，默认输出 `merged_Hps.h5`；
- 其他情况默认输出 `merged.h5`。

只校验输入文件而不生成输出：

```text
python hdf5_merge.py 182Vps.h5 352Vps.h5 --validate-only
```

如果目标文件已经存在，工具默认拒绝覆盖。确认可以覆盖时显式使用：

```text
python hdf5_merge.py 182Vps.h5 352Vps.h5 --output merged_Vps.h5 --force
```

## 校验和安全写出

合并前会检查：

- 两个输入文件是否存在且可以打开；
- 必需的根 Group 是否存在；
- 重叠路径的节点类型、Dataset 类型和形状是否兼容。

输出先写入同目录临时文件，写入完成后重新遍历校验，成功后才替换为目标文件。失败时会清理临时文件，原始输入文件不会被修改。

## 测试

运行单元测试：

```text
python -m unittest -v
```

测试覆盖：

- 不同场景 Group 的并集合并；
- 第一个文件优先的重复 Group 行为；
- Group/Dataset 类型冲突的提前失败。

## 项目文件

- `hdf5_merge.py`：命令行工具实现；
- `test_hdf5_merge.py`：单元测试；
- `requirements.txt`：Python 依赖；
- `*.h5`：本地输入和合并结果数据，不纳入 Git 版本控制。
