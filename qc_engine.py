from typing import List, Dict, Any, Optional, Tuple, Callable
# 导入数据结构
from data_parser import Point, AnnotationFeature


class QCResult:
    """质控检查结果"""

    def __init__(self, rule_id: str, status: str, message: str, feature_labels: List[str]):
        self.rule_id = rule_id
        self.status = status  # 'Pass', 'Fail', 'Warning', 'Not Applicable'
        self.message = message
        self.feature_labels = feature_labels


class QualityController:
    """核心质控引擎：在归一化和映射后的数据上执行规则检查。"""

    # 定义浮点数比较的容忍度 (在 1000x1000 空间内，5个像素的容忍度)
    POSITION_TOLERANCE = 5.0

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.rules = self.config.get('rules', [])
        self.normalization_scale = self.config['config']['normalization_scale']
        self.vertebra_range_groups = config.get('vertebra_range_groups', {})
        # 内部排序参考列表（包含 C0-L6）
        self.vertebra_order_list = config['config']['standard_spinal_sequence']
        self.vertebra_order = {label: i for i, label in enumerate(self.vertebra_order_list)}

    def _get_feature_center(self, annotations: List[AnnotationFeature], label: str) -> Optional[Point]:
        """
        获取标签的中心点。
        如果真实标注中不存在，则为椎体返回模拟的中心点（用于相对位置检查的参照）。
        """
        feature = next((f for f in annotations if f.label == label and f.center), None)
        if feature:
            return feature.center

        # 如果是椎体标签（例如 L5, T1），且真实数据中不存在，则返回模拟中心点
        if label in self.vertebra_order:
            try:
                # 基于椎体序号，计算一个模拟的归一化 Y 坐标
                order_index = self.vertebra_order.get(label)
                if order_index is not None:
                    # 假设 C0=50, L5=800，线性递增
                    y = 50 + order_index * (750 / len(self.vertebra_order_list))
                    return Point(500, y)
            except ValueError:
                pass
        return None

    def _check_sequence(self, annotations: List[AnnotationFeature], expected_labels: List[str], target_type: str) -> \
            Tuple[bool, str]:
        """检查特征 (如分割区域) 的 Y 轴顺序是否正确 (从上到下递增)"""
        ordered_features = []
        # 只检查在列表中且在标注数据中存在的标签
        for label in expected_labels:
            feature = next((a for a in annotations if a.label == label and a.type == target_type), None)
            if feature and feature.center:
                ordered_features.append((label, feature.center.y))

        if len(ordered_features) < 2:
            return True, "样本数量不足，无法检查顺序。"

        prev_label = None
        prev_y = -float('inf')  # 确保第一个元素的检查通过
        is_correct = True
        error_pairs = []

        for label, y in ordered_features:
            # 检查当前 Y 是否小于前一个 Y (即向上漂移)
            # 使用容忍度进行比较: 如果 y < prev_y - tolerance，则认为顺序错误
            if y < prev_y - self.POSITION_TOLERANCE:
                is_correct = False
                # 记录 (前一个标签, 当前标签) 形成错误对
                error_pairs.append((prev_label, label))

            prev_y = y
            prev_label = label

        if is_correct:
            return True, "标注顺序 (Y轴) 正确。"
        else:
            # 优化错误信息
            error_msg = f"发现 Y 坐标递减的椎体顺序错误。例如: "
            error_msg += "; ".join([
                                       f"'{p[0]}'({self._get_feature_center(annotations, p[0]).y:.1f}) 应在 '{p[1]}'({self._get_feature_center(annotations, p[1]).y:.1f}) 上方"
                                       for p in error_pairs[:3]])
            return False, error_msg

    def _execute_point_position_check(self, rule: Dict[str, Any], annotations: List[AnnotationFeature]) -> QCResult:
        """执行点标注的存在性和位置检查 (绝对/相对位置)"""
        params = rule['params']
        # 初始化规则状态，优先级顺序：Fail > Warning > Pass
        rule_status = 'Pass'
        messages: List[str] = []
        feature_labels: List[str] = []

        # 1. 存在性检查 (强制 Fail)
        for target in params['target_labels']:
            feature = next((a for a in annotations if a.label == target['label']), None)
            if target['required'] and not feature:
                rule_status = 'Fail'
                messages.append(f"【漏标/Fail】: 必需标签 '{target['label']}' 未找到。")
            elif feature:
                feature_labels.append(target['label'])

        # 2. 位置检查
        for position_rule in params.get('position_rules', []):
            target_label = position_rule['target']
            target_feature = next((a for a in annotations if a.label == target_label and a.center), None)

            if not target_feature:
                continue

            center = target_feature.center
            passed = True
            current_level = 'Pass'

            # 确定检查类型和级别
            if position_rule['check'] == "ABSOLUTE_X":
                # 左右颠倒 (ABSOLUTE_X) 视为严重错误 (Fail)
                threshold = position_rule['threshold']
                operator = position_rule['operator']
                current_level = 'Fail'

                value = center.x
                check_dim = 'X轴'
                actual = f"{value:.1f}"
                expected = f"{operator}{threshold}"

                if operator == '<':
                    passed = value < threshold + self.POSITION_TOLERANCE
                elif operator == '>':
                    passed = value > threshold - self.POSITION_TOLERANCE

            elif position_rule['check'].startswith("RELATIVE"):
                # 相对位置偏差 (RELATIVE_Y/X) 视为警告 (Warning)
                relative_label = position_rule['relative_to']
                relative_center = self._get_feature_center(annotations, relative_label)

                if not relative_center:
                    if rule_status != 'Fail': rule_status = 'Warning'
                    messages.append(f"【警告】: 参考标签 '{relative_label}' 缺失，无法进行相对检查。")
                    continue

                operator = position_rule['operator']
                current_level = 'Warning'

                if position_rule['check'] == 'RELATIVE_Y':
                    value, relative_value = center.y, relative_center.y
                    check_dim = 'Y轴'
                else:
                    value, relative_value = center.x, relative_center.x
                    check_dim = 'X轴'

                actual = f"{check_dim}={value:.1f}"
                expected = f"相对{relative_label} ({check_dim}={relative_value:.1f}) {operator}"

                if operator == '<':
                    passed = value < relative_value + self.POSITION_TOLERANCE
                elif operator == '>':
                    passed = value > relative_value - self.POSITION_TOLERANCE

            if not passed:
                # 更新规则状态为最高优先级
                if current_level == 'Fail':
                    rule_status = 'Fail'
                elif current_level == 'Warning' and rule_status == 'Pass':
                    rule_status = 'Warning'

                messages.append(
                    f"【错位/{current_level}】: 标签 '{target_label}' 位置错误 ({position_rule['message']})。"
                    f" 实际{check_dim}: {actual}, 预期: {expected}。"
                )

        final_message = "通过。"
        if messages:
            final_message = "; ".join(messages)

        # 如果规则状态仍是 Pass，但收集到了 Warning 消息，提升状态为 Warning
        if rule_status == 'Pass' and any('Warning' in msg for msg in messages):
            rule_status = 'Warning'

        if final_message == "通过。" and messages:
            final_message = "; ".join(messages)

        return QCResult(rule['id'], rule_status, final_message, feature_labels)

    def _execute_segmentation_completeness_check(self, rule: Dict[str, Any],
                                                 annotations: List[AnnotationFeature]) -> QCResult:
        """执行分割区域的完整性、多标漏标和顺序检查。多标漏标和顺序错误为 Fail 级别。"""
        params = rule['params']
        rule_status = 'Pass'
        messages: List[str] = []

        # --- 1. 必需标签和范围 ---
        required_labels_group_name = params.get('required_labels_group')
        required_labels_base = self.vertebra_range_groups.get(required_labels_group_name, [])
        required_labels = set(required_labels_base)
        optional_labels = set(params.get('optional_labels', []))
        all_expected_labels = required_labels.union(optional_labels)
        label_type = params['label_type']

        segmentations = [a for a in annotations if a.type == label_type]
        present_labels = {a.label for a in segmentations}

        # --- 2. 漏标检查 (Fail) ---
        missing_required = [label for label in required_labels if label not in present_labels]
        required_min_count = params.get('required_min_count', len(required_labels))

        if len(required_labels) - len(missing_required) < required_min_count:
            rule_status = 'Fail'
            messages.append(
                f"【严重漏标/Fail】: 必需标签数量 ({len(required_labels) - len(missing_required)}) 小于最小要求 ({required_min_count})。缺少: {', '.join(missing_required[:5])}...")
        elif missing_required:
            if rule_status == 'Pass': rule_status = 'Warning'
            messages.append(
                f"【必需漏标/Warning】: 缺少 {len(missing_required)} 个必需椎体 ({', '.join(missing_required[:5])}...)，可能存在误标。")

        # --- 3. 多标检查 (Warning/Fail) ---
        extra = [label for label in present_labels if label not in all_expected_labels]
        if extra:
            if rule_status != 'Fail': rule_status = 'Warning'
            messages.append(f"【多标/Warning】: 存在 {len(extra)} 个非预期分割 ({', '.join(extra[:3])}...)。")

        # --- 4. 特殊椎体和 L5/L6 检查 (Warning) ---
        if 'L5' in required_labels_base and 'L5' not in present_labels:
            if 'L4' in required_labels_base and 'L4' in present_labels and rule_status != 'Fail':
                rule_status = 'Warning'
                messages.append("【L5缺失/Warning】: L5缺失，请确认是否为骶化或漏标。")

        present_optional = [label for label in optional_labels if label in present_labels]
        if present_optional:
            messages.append(f"【特殊椎体/Warning】: 检测到可选椎体 {', '.join(present_optional)}。")

        # --- 5. 顺序检查 (Fail) ---
        present_expected = present_labels.intersection(all_expected_labels)
        sequence_check_labels = sorted(list(present_expected),
                                       key=lambda x: self.vertebra_order.get(x, len(self.vertebra_order_list)))

        if params.get('sequence_check', False):
            is_correct, seq_msg = self._check_sequence(annotations, sequence_check_labels, label_type)
            if not is_correct:
                rule_status = 'Fail'
                messages.append(f"【顺序错误/Fail】: {seq_msg}")
            elif not missing_required and present_optional and not extra and rule_status == 'Pass':
                messages.append("椎体分割（包含特殊椎体）顺序正确。")
            elif not missing_required and not present_optional and not extra and rule_status == 'Pass':
                messages.append("椎体分割顺序正确。")

        final_message = "通过。"
        if messages:
            final_message = "; ".join(messages)

        return QCResult(rule['id'], rule_status, final_message, list(all_expected_labels))

    def run_qc(self, annotations: List[AnnotationFeature], current_view: str) -> List[QCResult]:
        """Runs all enabled rules for the given view and annotations."""
        results: List[QCResult] = []

        view_annotations = [a for a in annotations if a.view == current_view]
        enabled_rules = [
            r for r in self.rules
            if r.get('enabled', False) and r.get('view') == current_view
        ]

        for rule in enabled_rules:
            check_type = rule['check_type']

            try:
                if check_type == 'POINT_POSITION_CHECK':
                    result = self._execute_point_position_check(rule, view_annotations)
                elif check_type == 'SEGMENTATION_COMPLETENESS':
                    result = self._execute_segmentation_completeness_check(rule, view_annotations)
                else:
                    result = QCResult(rule['id'], 'Warning', f"未知检查类型: {check_type}", [])

                # Prepend rule name to message for cleaner reporting in run_qc.py
                result.message = f"{rule.get('name_cn', rule['id'])}: {result.message}"
                results.append(result)
            except Exception as e:
                results.append(QCResult(rule['id'], 'Fail', f"规则执行错误: {e}", []))

        return results