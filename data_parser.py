import json
import os
from typing import List, Dict, Any, Optional
import nrrd


# --- 1. 数据结构定义 (保持不变) ---

class Point:
    """归一化坐标点 (0-1000)"""

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


class AnnotationFeature:
    """统一标注特征接口 (内部使用医学标准标签)"""

    def __init__(self, label: str, type: str, points: List[Point], view: str):
        self.label = label
        self.type = type
        self.points = points
        self.view = view
        self.center: Optional[Point] = self._calculate_center()

    def _calculate_center(self) -> Optional[Point]:
        """计算标注特征的中心点"""
        if not self.points:
            return None
        sum_x = sum(p.x for p in self.points)
        sum_y = sum(p.y for p in self.points)
        count = len(self.points)
        return Point(sum_x / count, sum_y / count)


# --- 2. 数据解析器 (Adapter for different annotation tools) ---

class DataParser:
    """数据解析器：负责加载数据、将实际标签映射为医学标准标签并归一化坐标。"""

    def __init__(self, normalization_scale: int, config: Dict[str, Any]):
        self.scale = normalization_scale
        self.config = config
        self.label_mapping = config.get('label_mapping', {})
        self.mirror_x = config['config'].get('mirror_x_axis', False)
        self._reverse_map: Dict[str, str] = {}

    def _get_effective_map(self, view: str) -> Dict[str, List[str]]:
        view_config = self.label_mapping.get(view)
        if not view_config:
            return {}
        current_map = view_config.get('standard_to_actual_map', {}).copy()
        extends_view = view_config.get('_extends')
        if extends_view:
            parent_map = self._get_effective_map(extends_view)
            effective_map = parent_map.copy()
            effective_map.update(current_map)
            return effective_map
        else:
            return current_map

    def _build_reverse_map(self, view: str) -> Dict[str, str]:
        reverse_map: Dict[str, str] = {}
        full_standard_map = self._get_effective_map(view)
        for standard_label, actual_labels in full_standard_map.items():
            if isinstance(actual_labels, list):
                for actual_label in actual_labels:
                    reverse_map[actual_label] = standard_label
        return reverse_map

    def _get_medical_label(self, actual_label: str, view: str) -> Optional[str]:
        self._reverse_map = self._build_reverse_map(view)
        return self._reverse_map.get(actual_label, None)

    def _normalize_point(self, x: float, y: float, img_w: int, img_h: int) -> Point:
        target_x = x
        if self.mirror_x:
            target_x = img_w - x
        norm_x = (target_x / img_w) * self.scale
        norm_y = (y / img_h) * self.scale
        return Point(norm_x, norm_y)

    def parse_labelme_json(self, json_filepath: str, view: str) -> List[AnnotationFeature]:
        if not os.path.exists(json_filepath):
            raise FileNotFoundError(f"LabelMe file not found: {json_filepath}")
        with open(json_filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        img_w = int(data.get("imageWidth", 1))
        img_h = int(data.get("imageHeight", 1))
        if img_w <= 0 or img_h <= 0:
            raise ValueError(f"Invalid image dimensions in LabelMe file: W={img_w}, H={img_h}")

        annotations: List[AnnotationFeature] = []
        for shape in data.get('shapes', []):
            actual_label = shape['label']
            shape_type = shape['shape_type']
            feature_type = 'point' if shape_type == 'point' else 'line' if shape_type == 'line' else 'polygon'
            standard_label = self._get_medical_label(actual_label, view)
            if not standard_label:
                continue
            normalized_points = [
                self._normalize_point(float(p[0]), float(p[1]), img_w, img_h)
                for p in shape.get('points', [])
            ]
            annotations.append(AnnotationFeature(
                label=standard_label,
                type=feature_type,
                points=normalized_points,
                view=view
            ))
        return annotations

    # --- Slicer 解析器核心逻辑 (分割标签获取) ---

    def _get_slicer_segmentation_labels(self, data_dir: str, view: str) -> List[str]:
        """
        [修复后的逻辑] 查找 .seg.nrrd 文件并从中提取实际分割标签。
        移除了 header_only 参数，以提高对旧版本 pynrrd 的兼容性。
        """
        for root, _, files in os.walk(data_dir):
            for file_name in files:
                # 兼容 Segmentation_X.seg.nrrd 命名模式
                if file_name.lower().endswith('.seg.nrrd'):
                    seg_file_path = os.path.join(root, file_name)
                    try:
                        # 修复：移除 header_only=True 参数，兼容旧版本 pynrrd
                        # 这将读取整个文件，然后获取 header
                        _, header = nrrd.read(seg_file_path)

                        actual_labels_found = []
                        # 查找所有与 Segment 相关的元数据键
                        segment_keys = [k for k in header.keys() if k.startswith('Segment')]

                        # Slicer 标签提取逻辑：
                        # 1. 收集所有 SegmentX_LabelValue 对应的 ID
                        # 2. 找到对应的 SegmentX_Name

                        segment_ids = {}  # { 'SegmentID': 'Actual_Label_Name' }

                        for key in segment_keys:
                            if key.endswith('_LabelValue'):
                                # SegmentXX_LabelValue -> XX
                                segment_base = key.replace('_LabelValue', '')

                                # 查找对应的 SegmentXX_Name
                                name_key = f'{segment_base}_Name'
                                actual_name = header.get(name_key)

                                if actual_name:
                                    segment_ids[segment_base] = actual_name

                        actual_labels_found = list(segment_ids.values())

                        if actual_labels_found:
                            print(f"Info: Found {len(actual_labels_found)} segmentation labels in {file_name} header.")
                        else:
                            print(f"Warning: Segmentation header found, but could not extract Segment_X_Name labels.")

                        return actual_labels_found

                    except Exception as e:
                        # 捕获读取失败的异常
                        print(f"Error: Failed to read NRRD metadata from {file_name}: {e}")
                        return []

        print("Warning: Segmentation file (*.seg.nrrd) not found.")
        return []

    # --- Slicer 解析器 (主函数) ---

    def parse_slicer_data_dir(self, data_dir: str, view: str) -> List[AnnotationFeature]:
        """
        解析 3D Slicer 的多文件结构 (directory)。
        1. 递归查找所有 .mrk.json 文件作为关键点，并进行动态归一化。
        2. 读取 .seg.nrrd 文件来获取实际分割标签。
        """
        annotations: List[AnnotationFeature] = []
        self._reverse_map = self._build_reverse_map(view)

        raw_keypoints: List[Dict[str, Any]] = []

        # 1. 递归查找和收集所有原始关键点 (保持不变)
        for root, _, files in os.walk(data_dir):
            for file_name in files:
                if file_name.lower().endswith('.mrk.json'):
                    actual_label_base = file_name.rsplit('.', 2)[0]
                    standard_label = self._get_medical_label(actual_label_base, view)

                    if not standard_label:
                        continue

                    keypoint_file = os.path.join(root, file_name)
                    try:
                        with open(keypoint_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        control_points = data.get('markups', [{}])[0].get('controlPoints', [])

                        for cp in control_points:
                            pos = cp.get('position', [])
                            if len(pos) >= 2:
                                raw_keypoints.append({
                                    'standard_label': standard_label,
                                    'x': float(pos[0]),
                                    'y': float(pos[1]),
                                    'type': 'point'
                                })

                    except Exception as e:
                        print(f"Warning: Failed to parse Slicer keypoint file {keypoint_file}: {e}")

        # 2. 动态归一化 (保持不变)
        if raw_keypoints:
            xs = [kp['x'] for kp in raw_keypoints]
            ys = [kp['y'] for kp in raw_keypoints]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            img_width = max(max_x - min_x, 1e-6)
            img_height = max(max_y - min_y, 1e-6)
            scale_f = float(self.scale)

            for kp in raw_keypoints:
                shifted_x = kp['x'] - min_x
                shifted_y = kp['y'] - min_y
                norm_x = (shifted_x / img_width) * scale_f
                norm_y = (shifted_y / img_height) * scale_f
                if self.mirror_x:
                    norm_x = scale_f - norm_x
                normalized_point = Point(norm_x, norm_y)

                annotations.append(AnnotationFeature(
                    label=kp['standard_label'],
                    type=kp['type'],
                    points=[normalized_point],
                    view=view
                ))
            print(
                f"Info: Slicer keypoints normalized using dynamic extent (X range: {img_width:.2f}, Y range: {img_height:.2f}).")
        else:
            print(f"Warning: No Slicer keypoint files (.mrk.json) found in {data_dir}. Skipping keypoint checks.")

        # 3. 获取并处理实际分割标签
        actual_segment_labels = self._get_slicer_segmentation_labels(data_dir, view)

        for actual_label in actual_segment_labels:
            # 这里的 actual_label 已经是 Slicer Segment Name
            standard_label = self._get_medical_label(actual_label, view)

            if standard_label:
                # 使用 Mock 中心点，但仅针对实际找到的标签
                annotations.append(AnnotationFeature(
                    label=standard_label,
                    type='polygon',
                    points=[Point(500, 500)],
                    view=view
                ))

        if actual_segment_labels:
            print(f"Info: Segment existence check finalized based on actual NRRD metadata.")

        return annotations

    def parse_data(self, file_or_dir_path: str, annotator_tool: str, view: str) -> List[AnnotationFeature]:
        """根据标注工具类型分派数据解析。"""
        if annotator_tool == 'labelme':
            return self.parse_labelme_json(file_or_dir_path, view)
        elif annotator_tool == 'slicer':
            if not os.path.isdir(file_or_dir_path):
                print(f"Error: Slicer tool requires a directory path, but got a file path: {file_or_dir_path}")
                return []
            return self.parse_slicer_data_dir(file_or_dir_path, view)
        else:
            raise ValueError(f"Unsupported annotator tool: {annotator_tool}")