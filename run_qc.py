import time
import json
import os
import re
from typing import Dict, Any, List, Optional, Tuple
# 导入模块化的组件
from data_parser import DataParser
from qc_engine import QualityController, QCResult

# Global storage for configuration
CONFIG: Dict[str, Any] = {}
# Global list to store all results for final reporting
ALL_CASE_RESULTS: List[Dict[str, Any]] = []


def load_config(config_path: str) -> bool:
    """加载 JSON 配置文件并执行配置适配"""
    global CONFIG
    if not os.path.exists(config_path):
        print(f"Error: Configuration file not found at {config_path}")
        return False
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            CONFIG = json.load(f)

        # ------------------------------------------------------------------
        # 配置适配层
        # 确保 QC 引擎运行所需的所有配置键都存在
        # ------------------------------------------------------------------
        if 'standard_spinal_sequence' in CONFIG['config'] and 'vertebra_labels' not in CONFIG['config']:
            CONFIG['config']['vertebra_labels'] = CONFIG['config']['standard_spinal_sequence']

        if 'current_run_context' not in CONFIG:
            raise KeyError("'current_run_context'")

        print(
            f"Configuration loaded successfully. Supported tools: {CONFIG['config']['supported_annotators']}")
        return True
    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse configuration JSON: {e}")
        return False
    except KeyError as e:
        print(f"Error: Configuration structure missing required key: {e}")
        return False
    except Exception as e:
        print(f"An unexpected error occurred during config loading: {e}")
        return False


def get_current_tool_config(tool_name: str) -> Optional[Dict[str, Any]]:
    """从配置中获取当前工具的结构配置模板（例如 'labelme_template'）"""
    data_structure_cfg = CONFIG.get('data_structure', {})
    # 查找对应的模板，例如 'labelme_template'
    return data_structure_cfg.get(f"{tool_name}_template")


def find_cases_and_process(base_data_path: str):
    """
    递归遍历数据集，根据配置的工具和模板匹配文件/目录，并运行 QC 引擎。
    """
    global ALL_CASE_RESULTS

    current_run_context = CONFIG.get('current_run_context', {})
    if not current_run_context:
        print("Error: 'current_run_context' block is missing from qc_config.json.")
        return

    # 1. 从新的集中块获取动态配置
    current_tool_name = current_run_context.get('annotator_tool')
    view = current_run_context.get('data_view')
    structure_id = current_run_context.get('structure_id')

    if not current_tool_name or not view or not structure_id:
        print("Error: 'annotator_tool', 'data_view' or 'structure_id' missing in 'current_run_context'.")
        return

    # 2. 从静态模板获取文件类型 (file_type)
    tool_cfg = get_current_tool_config(current_tool_name)

    if not tool_cfg:
        print(f"Error: Configuration template for tool '{current_tool_name}' not found in 'data_structure'.")
        return

    # 3. 从模板中解包文件类型 (file_type)
    file_type = tool_cfg.get('file_type', 'single_file')

    # ---------------------------------------------------------------
    # 原始逻辑（保持不变）
    # ---------------------------------------------------------------
    path_pattern_str = CONFIG['path_templates'].get(structure_id, "")
    if not path_pattern_str:
        print(f"Error: Path template '{structure_id}' not found in 'path_templates'.")
        return

    path_pattern_regex = re.sub(r'\{(\w+)\}', r'(?P<\1>[^/]+)', path_pattern_str)
    path_pattern_regex = '^' + path_pattern_regex + '$'

    parser = DataParser(
        normalization_scale=CONFIG['config']['normalization_scale'],
        config=CONFIG
    )
    qc_controller = QualityController(CONFIG)

    print(f"Starting QC for tool: {current_tool_name} (View: {view}, Structure: {structure_id})")

    # --- 遍历逻辑 ---

    for root, dirs, files in os.walk(base_data_path):

        # 1. 针对目录结构 (如 Slicer)
        if file_type == 'directory':
            relative_path = os.path.relpath(root, base_data_path).replace(os.sep, '/')
            if relative_path == '.':
                continue

            match = re.match(path_pattern_regex, relative_path)

            if match:
                match_vars = match.groupdict()
                target_path_full = root
                case_id = match_vars.get('CASE', os.path.basename(root))

                print(f"\n======== [Processing Dir: {case_id} ({current_tool_name}/{view})] ========")

                try:
                    annotations = parser.parse_data(target_path_full, current_tool_name, view)

                    if annotations:
                        results = qc_controller.run_qc(annotations, view)

                        ALL_CASE_RESULTS.append({
                            'case_id': case_id,
                            'tool': current_tool_name,
                            'view': view,
                            'details': results
                        })

                        print_results(results, f"{case_id} ({view}/{current_tool_name})", use_color=True)

                    else:
                        print(f"Warning: No valid annotations found in directory {target_path_full}.")

                except Exception as e:
                    print(f"CRITICAL ERROR processing directory {target_path_full}: {e}")

        # 2. 针对单个文件结构 (如 LabelMe)
        elif file_type == 'single_file':
            for file_name_with_ext in files:

                relative_path = os.path.relpath(os.path.join(root, file_name_with_ext), base_data_path).replace(os.sep,
                                                                                                                '/')

                match = re.match(path_pattern_regex, relative_path)

                if match:
                    target_path_full = os.path.join(root, file_name_with_ext)
                    match_vars = match.groupdict()
                    case_id = match_vars.get('CASE', os.path.splitext(file_name_with_ext)[0])

                    print(f"\n======== [Processing File: {case_id} ({current_tool_name}/{view})] ========")

                    try:
                        annotations = parser.parse_data(target_path_full, current_tool_name, view)

                        if annotations:
                            results = qc_controller.run_qc(annotations, view)

                            ALL_CASE_RESULTS.append({
                                'case_id': case_id,
                                'tool': current_tool_name,
                                'view': view,
                                'details': results
                            })

                            print_results(results, f"{case_id} ({view}/{current_tool_name})", use_color=True)

                        else:
                            print(f"Warning: No valid annotations found in file {target_path_full}.")

                    except Exception as e:
                        print(f"CRITICAL ERROR processing file {target_path_full}: {e}")
        else:
            print(f"Error: Unknown file_type '{file_type}' configured for tool '{current_tool_name}'. Skipping.")
            return


def print_results(results: List[QCResult], case_name: str, use_color: bool = True):
    """格式化并打印结果到终端。"""
    fail_count = sum(1 for r in results if r.status == 'Fail')
    warn_count = sum(1 for r in results if r.status == 'Warning')

    FAIL_COLOR = '\033[91m' if use_color else ''
    WARNING_COLOR = '\033[93m' if use_color else ''
    PASS_COLOR = '\033[92m' if use_color else ''
    END_COLOR = '\033[0m' if use_color else ''

    print(f"\n--- Report for {case_name} ---")

    if fail_count > 0:
        overall_text = f"{FAIL_COLOR}Overall Result: FAIL ({fail_count} errors, {warn_count} warnings){END_COLOR}"
    elif warn_count > 0:
        overall_text = f"{WARNING_COLOR}Overall Result: WARNING (0 errors, {warn_count} warnings){END_COLOR}"
    else:
        overall_text = f"{PASS_COLOR}Overall Result: PASS (All checks passed){END_COLOR}"

    print(overall_text)

    for r in results:
        if r.status == 'Fail':
            color = FAIL_COLOR
        elif r.status == 'Warning':
            color = WARNING_COLOR
        else:
            color = PASS_COLOR

        print(f"{color}  [{r.status.upper()}] {r.message}{END_COLOR}")


def generate_report(base_path: str):
    """
    汇总所有案例结果并生成纯文本报告文件。
    """
    global ALL_CASE_RESULTS

    total_cases = len(ALL_CASE_RESULTS)
    fail_cases = 0
    warning_cases = 0
    not_passed_cases = 0

    def check_if_passed(results: List[QCResult]) -> Tuple[bool, bool, bool]:
        has_fail = any(r.status == 'Fail' for r in results)
        has_warning = any(r.status == 'Warning' for r in results)
        is_passed = not has_fail and not has_warning
        return is_passed, has_fail, has_warning

    summary_data = []
    for res in ALL_CASE_RESULTS:
        passed, has_fail, has_warning = check_if_passed(res['details'])

        if has_fail:
            fail_cases += 1
            not_passed_cases += 1
        elif has_warning:
            warning_cases += 1
            not_passed_cases += 1

        summary_data.append({
            'case_id': res['case_id'],
            'tool': res['tool'],
            'view': res['view'],
            'status': 'Pass' if passed else ('Fail' if has_fail else 'Warning'),
            'details': res['details']
        })

    # --- 构造新的文件名 ---
    # 1. 提取数据集根目录名（去除路径和斜杠）
    base_name = os.path.basename(os.path.normpath(base_path))
    if not base_name:
        base_name = "dataset"

    # 2. 构造报告文件名：qc_report_summary_{base_name}.txt
    report_filename = f"qc_report_summary_{base_name}.txt"

    # 报告输出到脚本所在的目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    report_path_full = os.path.join(script_dir, report_filename)

    # 写入报告文件
    try:
        with open(report_path_full, 'w', encoding='utf-8') as f:
            f.write("QC Report Summary\n")
            f.write("==================\n")
            try:
                import time
                f.write(f"Execution Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}\n")
            except:
                f.write("Execution Timestamp: N/A\n")

            # 从新的集中配置块读取信息
            run_context = CONFIG.get('current_run_context', {})
            f.write(f"Annotator Tool: {run_context.get('annotator_tool', 'N/A')}\n")
            f.write(f"View Used: {run_context.get('data_view', 'N/A')}\n")
            f.write(f"Structure ID: {run_context.get('structure_id', 'N/A')}\n")
            f.write(f"Data Path Used: {base_path}\n")
            f.write(f"Total Cases Processed: {total_cases}\n")
            f.write(f"Cases Passed: {total_cases - not_passed_cases}\n")
            f.write(f"Cases Not Passed: {not_passed_cases} (Fail: {fail_cases}, Warning: {warning_cases})\n")
            f.write("==================\n\n")

            issue_found = False

            def sort_key(res):
                if res['status'] in ('Fail', 'FAIL_CRITICAL'):
                    return 0
                if res['status'] == 'Warning':
                    return 1
                return 2

            sorted_results = sorted(summary_data, key=sort_key)

            for res in sorted_results:
                if res['status'] == 'Pass':
                    continue

                issue_found = True

                f.write(f"\n--- CASE: {res['case_id']} ({res['status'].upper()}) ---\n")
                f.write(f"[VIEW/TOOL]: {res['view']}/{res['tool']}\n")
                f.write("--- ISSUES ---\n")

                for detail in res['details']:
                    if isinstance(detail, QCResult) and detail.status != 'Pass':
                        f.write(f"  [{detail.status.upper()}]: {detail.message}\n")

                f.write("----------------\n")

            if not issue_found:
                f.write("\nCongratulations! All processed cases passed QC checks.\n")

        print(f"\n--- QC Reporting ---\nSuccessfully generated summary report: {report_path_full}")
        print(
            f"Total Cases: {total_cases}. Not Passed: {not_passed_cases} (Fail: {fail_cases}, Warning: {warning_cases}).")
    except PermissionError as e:
        print(f"\nCRITICAL REPORTING ERROR: Failed to write summary report to {report_path_full}.")
        print(f"Please check file permissions or run the script from a directory with write access.")
        print(f"Original Error: {e}")
    except Exception as e:
        print(f"\nCRITICAL REPORTING ERROR: An unexpected error occurred during report generation: {e}")


if __name__ == "__main__":
    # 记录开始时间
    start_time = time.time()

    if not load_config('qc_config.json'):
        exit(1)

    run_context = CONFIG.get('current_run_context')
    if not run_context:
        print("Error: 'current_run_context' block is missing from qc_config.json.")
        exit(1)

    BASE_PATH = run_context.get('base_data_path')
    if not BASE_PATH:
        print("Error: 'base_data_path' is missing from 'current_run_context'.")
        exit(1)

    find_cases_and_process(BASE_PATH)

    generate_report(BASE_PATH)

    # 计算并打印运行时间
    end_time = time.time()
    duration = end_time - start_time
    print(f"\nTotal execution time: {duration:.2f} seconds")