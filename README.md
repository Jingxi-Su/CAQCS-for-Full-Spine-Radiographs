<p align="right">
  English | <a href="README.md">中文</a>
</p>

# Configurable Whole-Spine X-ray Annotation Quality Control System

This project is a **pure Python, configuration-driven** automated Quality Control (QC) system designed for **whole-spine X-ray annotation validation**.  
It aims to replace time-consuming and inconsistent manual double-blind reviews by introducing **rule-based, topology-aware, and reproducible QC logic**.

By decoupling **medical topology knowledge**, **annotation conventions**, and **dataset file structures**, the system can flexibly adapt to different annotation tools and data organizations, while producing **strict, graded QC reports** with clear `Fail` / `Warning` distinctions.

---

## System Architecture and Core Modules

The system consists of **four highly decoupled Python modules** and **one JSON configuration file**:

| File | Role | Responsibility |
| :--- | :--- | :--- |
| **`qc_config.json`** | **Configuration Center** | Defines QC rules, label mappings, validation thresholds, **path templates** (`path_templates`), and the active execution environment (`current_run_context`). |
| **`data_parser.py`** | **Data Adaptation Layer** | Parses native annotation formats from different tools (e.g., LabelMe JSON, 3D Slicer NRRD/JSON), performs **label mapping** and **coordinate normalization**, and outputs a unified internal format for the QC engine. |
| **`qc_engine.py`** | **Rule-based QC Engine** | Executes all rule-driven checks (existence, topology order, relative position, etc.) and determines the severity level (`Fail` or `Warning`) for each violation. |
| **`run_qc.py`** | **Execution & Report Generator** | Loads configurations, recursively traverses datasets, dispatches the QC engine, and generates a unified summary report: **`qc_report_summary_{dataset_name}.txt`**. |

---

## 🚀 Quick Start

### 1. Environment Setup

Ensure a working Python environment. All scripts and `qc_config.json` should be placed in the same directory.  
The system relies only on the Python standard library and the `nrrd` package (required for parsing Slicer NRRD files).

### 2. Configuration

Edit the `current_run_context` section in `qc_config.json` to match your dataset paths, annotation tool, view type, and **data structure**.

### 3. Run QC

~~~bash
python run_qc.py
~~~

After execution, a summary report named  
**`qc_report_summary_{dataset_name}.txt`**  
will be generated in the script directory.

---

## ⚙️ Configuration Details (`qc_config.json`)

### 1. Execution Context (`current_run_context`)

This section defines the **dynamic runtime context** for each QC execution.

| Field | Description | Example |
| :--- | :--- | :--- |
| `annotator_tool` | Annotation tool used for the current run. | `"labelme"` / `"slicer"` |
| `data_view` | View type of the dataset. | `"AP"` / `"LAT"` |
| `base_data_path` | Root directory of the dataset (recursively scanned). | `"./test_data"` |
| `structure_id` | ID referencing `path_templates`, defining file/directory layout. | `"FLAT_FILE"` / `"SLICER_DIR"` |

#### Path Template Presets (`path_templates`)

| Template ID | Structure Description | Path Pattern |
| :--- | :--- | :--- |
| `FLAT_FILE` | Root / Annotation File | `"{FILE_NAME}.json"` |
| `NESTED_PATIENT` | Root / PatientID / Annotation File | `"{CASE}/{FILE_NAME}.json"` |
| `NESTED_SEQUENCE` | Root / PatientID / SequenceID / Annotation File | `"{CASE}/{SEQUENCE_ID}/{FILE_NAME}.json"` |
| `SLICER_DIR` | Directory-based tools such as Slicer | `"{CASE}/{SEQUENCE_ID}"` |

---

### 2. Label Mapping (`label_mapping`)

This section maps **annotator-defined raw labels** to **standardized medical labels** used internally by the QC system.

For example, labels such as `C7_seg` or `Segment_0` can be mapped to the standard label `C7`.

| Field | Description | Inheritance |
| :--- | :--- | :--- |
| `COMMON` | View-independent labels (primarily vertebral segmentations). | — |
| `AP` / `LAT` | Extend `COMMON` and add view-specific keypoint labels (e.g., `Left_Clavicle_Highest`). | Uses `"_extends": "COMMON"` |

---

### 3. QC Rules and Severity Levels (`rules`)

All QC rules are **fully configurable** and can be enabled or disabled using the `enabled` flag.

#### Severity Level Definition

| Level | Severity | Typical Triggers |
| :--- | :--- | :--- |
| **FAIL** | Critical errors that must be corrected. | Missing required labels, left–right inversion of keypoints (`ABSOLUTE_X`), incorrect vertebral order (`sequence_check`). |
| **WARNING** | Minor deviations or data variations worth review or documentation. | Partial missing required labels, relative position deviation (`RELATIVE_Y/X`), extra annotations, presence of optional vertebrae (e.g., `T13`, `L6`). |

---

#### Rule Type: Keypoint Position Check (`POINT_POSITION_CHECK`)

Validates the **existence and spatial correctness** of keypoints (`point` or `line`).

| Check | Description |
| :--- | :--- |
| **Existence** | Ensures all labels in `target_labels` are present. |
| **Left / Right Constraint** | Validates whether a keypoint lies in the correct half of the normalized image (`ABSOLUTE_X`). |
| **Relative Topology** | Checks spatial relationships between medical landmarks or vertebral center proxies (`RELATIVE_Y`, `RELATIVE_X`). |
| **Normalization** | All coordinates are normalized to a **0–1000** coordinate space. |

---

#### Rule Type: Segmentation Completeness (`SEGMENTATION_COMPLETENESS`)

Validates **vertebral segmentation integrity and topology**.

| Check | Description | Config Field |
| :--- | :--- | :--- |
| **Completeness** | Ensures all required vertebrae are annotated. | `required_labels_group` |
| **Topological Order** | Verifies correct vertebral order along the Y-axis (C0 → L6, increasing Y). | `sequence_check: true` |
| **Optional / Extra Labels** | Detects optional or extra vertebrae (e.g., `L6`, `T13`). | `optional_labels` |

---

## 📌 Design Philosophy

- Configuration over hard-coding  
- Topology-aware QC instead of pixel heuristics  
- Strict error grading for large-scale annotation management  
- Reproducible and auditable QC results suitable for research publication  

---

## 📄 Output

- Unified QC summary report:
  ~~~text
  qc_report_summary_{dataset_name}.txt
  ~~~
- Clear distinction between **Fail** and **Warning**
- Designed for large datasets and multi-annotator scenarios
