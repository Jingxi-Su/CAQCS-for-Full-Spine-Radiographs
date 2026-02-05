# 可配置的全脊柱 X 光片标注质控系统 (QC)

本系统是一套**纯 Python、配置驱动**的自动化质控（QC）解决方案，旨在替代耗时且不一致的人工双盲标注。通过将医学拓扑知识、标注规范和文件结构解耦，系统能够灵活适应不同的数据源，并提供严格的 Fail/Warning 分级报告。

## 核心文件及模块结构

本系统由四个高度解耦的 Python 文件和一个 JSON 配置文件构成：

| 文件名 | 模块化角色 | 主要职责 |
| :--- | :--- | :--- |
| **`qc_config.json`** | **配置中心** | 定义 QC 规则、标签映射、检查阈值、**路径模板** (`path_templates`) 和当前运行环境 (`current_run_context`)。 |
| **`data_parser.py`** | **数据适配层** | 读取各种标注工具的原生文件（如 LabelMe JSON, Slicer NRRD/JSON），进行**标签映射**和**坐标归一化**，确保数据符合 QC 引擎的标准格式。 |
| **`qc_engine.py`** | **核心规则引擎** | 执行所有规则驱动的检查逻辑（存在性、拓扑顺序、相对位置等）。负责确定每个检查结果的 `Fail`/`Warning` 级别。 |
| **`run_qc.py`** | **执行器与报告生成** | 加载配置、递归遍历数据集、调度 QC 引擎，并在运行结束后生成统一的 **`qc_report_summary_{dataset_name}.txt`** 汇总报告。 |

## 快速运行指南

1.  **环境准备**: 确保 Python 环境已就绪，且所有脚本和 `qc_config.json` 位于同一目录下。系统依赖标准库以及 `nrrd` 库（用于 Slicer NRRD 文件解析）。

2.  **配置设定**: 根据实际数据路径、标注工具、视图和**数据结构**，编辑 `qc_config.json` 中的 `current_run_context` 块。

3.  **运行脚本**:

    ```bash
    python run_qc.py
    ```

    *运行后，系统将自动在脚本所在目录生成 `qc_report_summary_{dataset_name}.txt` 汇总报告。*

## 核心配置详解 (`qc_config.json`)

### 1. 运行上下文配置 (`current_run_context`)

该块是每次运行的核心动态配置，指定了本次 QC 检查的目标、工具和数据结构。

| 字段 | 作用 | 示例值 |
| :--- | :--- | :--- |
| `annotator_tool` | 当前要运行检查的标注工具名称。 | `"labelme"` 或 `"slicer"` |
| `data_view` | 明确指定当前数据集的视图类型。 | `"AP"` 或 `"LAT"` |
| `base_data_path` | 数据集根目录路径，用于递归搜索。 | `"./test_data"` |
| `structure_id` | 引用 `path_templates` 中的 ID，决定文件/目录的匹配模式。 | `"FLAT_FILE"` 或 `"SLICER_DIR"` |

#### 路径模板 (`path_templates`) 预设

| 模板 ID | 结构描述 | 模板路径（用于匹配） |
| :--- | :--- | :--- |
| `FLAT_FILE` | `总文件夹 / 标注文件` | `"{FILE_NAME}.json"` |
| `NESTED_PATIENT` | `总文件夹 / 患者ID / 标注文件` | `"{CASE}/{FILE_NAME}.json"` |
| `NESTED_SEQUENCE` | `总文件夹 / 患者ID / 序列ID / 标注文件` | `"{CASE}/{SEQUENCE_ID}/{FILE_NAME}.json"` |
| `SLICER_DIR` | *（针对 Slicer 等多文件工具的目录结构）* | `"{CASE}/{SEQUENCE_ID}"` |

### 2. 标签映射配置 (`label_mapping`)

将标注员使用的**实际标签**映射为 QC 系统内部使用的**医学标准标签**，以实现标签名的解耦。解析器使用此映射将原始标签（如 `C7_seg`, `Segment_0`）转换为标准标签（如 `C7`）。

| 字段 | 作用 | 继承关系 |
| :--- | :--- | :--- |
| `COMMON` | 适用于所有视图的通用标签（主要用于椎体分割标签）。 | 无 |
| `AP`/`LAT` | 继承 `COMMON` 的映射并添加特定视图的关键点标签（如 `Left_Clavicle_Highest`）。 | 使用 `"_extends": "COMMON"` 继承 |

### 3. QC 规则定义 (`rules`) - 错误级别划分

所有规则都是可配置的，通过 `enabled` 字段控制是否激活。

**规则级别划分原则：**

| 级别 | 严重性 | 触发条件示例 |
| :--- | :--- | :--- |
| **FAIL (错误)** | 严重拓扑错误或数据完整性缺失，必须修复。 | 必需标签**漏标**、点标注**左右颠倒** (`ABSOLUTE_X`)、椎体**顺序错误** (`sequence_check`)。 |
| **WARNING (警告)** | 轻微偏差或数据变异，建议复查或记录。 | **必需标签部分漏标**、**相对位置偏差** (`RELATIVE_Y/X`)、**多标**（标注了非预期标签）、检测到可选椎体（如 `T13`, `L6`）。 |

#### 规则类型：关键点位置检查 (`POINT_POSITION_CHECK`)

用于检查关键点（`point` 或 `line` 类型）的存在性和归一化后的位置。

| 检查项 | 描述 | 关键点 |
| :--- | :--- | :--- |
| **存在性** | 检查 `target_labels` 中的点是否被标注。 | `required: true` |
| **左右定位** | 检查点是否在归一化图像（0-1000）的左右半边。 | `ABSOLUTE_X` |
| **方向拓扑** | 检查点相对于另一个医学参照点（或椎体模拟中心点）的相对位置。 | `RELATIVE_Y`, `RELATIVE_X` |
| **归一化：** 所有坐标都归一化到 $0 \sim 1000$ 的空间内。

#### 规则类型：分割完整性检查 (`SEGMENTATION_COMPLETENESS`)

用于检查分割区域（`polygon` 类型，通常是椎体分割）的完整性和拓扑结构。

| 检查项 | 描述 | 配置字段 |
| :--- | :--- | :--- |
| **完整性** | 检查 `required_labels_group` 定义的必需椎体范围是否被标注。 | `required_labels_group` |
| **拓扑顺序** | 检查已标注的椎体沿 Y 轴的顺序是否正确（从 C0 到 L6 Y 值递增）。 | `sequence_check: true` |
| **多标/可选** | 检查是否有多余的或可选的标签（如 `L6`, `T13`）。 | `optional_labels` |