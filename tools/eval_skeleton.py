from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List

import networkx as nx
from shapely.geometry import LineString

try:
    import geopandas as gpd
except ModuleNotFoundError:
    gpd = None


def _line_strings(gdf: Any) -> List[LineString]:
    return [geom for geom in gdf.geometry if isinstance(geom, LineString) and not geom.is_empty]


def build_graph(lines: List[LineString], precision: int = 3) -> nx.Graph:
    graph = nx.Graph()
    for line in lines:
        start = (round(line.coords[0][0], precision), round(line.coords[0][1], precision))
        end = (round(line.coords[-1][0], precision), round(line.coords[-1][1], precision))
        if start == end:
            continue
        graph.add_edge(start, end, weight=float(line.length), geometry=line)
    return graph


def outside_ratio(lines: List[LineString], polygon, sample_step: float) -> float:
    outside_samples = 0
    total_samples = 0
    for line in lines:
        if line.length <= 0:
            continue
        n = max(2, int(math.ceil(line.length / sample_step)) + 1)
        for i in range(n):
            point = line.interpolate((i / (n - 1)) * line.length)
            total_samples += 1
            if not polygon.covers(point):
                outside_samples += 1
    if total_samples == 0:
        return 0.0
    return outside_samples / total_samples


def has_parallel_pair(lines: List[LineString], max_dist: float, max_angle_deg: float) -> bool:
    if len(lines) < 2:
        return False
    for i in range(len(lines)):
        line_a = lines[i]
        ax, ay = line_a.coords[-1][0] - line_a.coords[0][0], line_a.coords[-1][1] - line_a.coords[0][1]
        a_len = math.hypot(ax, ay)
        if a_len == 0:
            continue
        for j in range(i + 1, len(lines)):
            line_b = lines[j]
            bx, by = line_b.coords[-1][0] - line_b.coords[0][0], line_b.coords[-1][1] - line_b.coords[0][1]
            b_len = math.hypot(bx, by)
            if b_len == 0:
                continue
            cosv = max(-1.0, min(1.0, (ax * bx + ay * by) / (a_len * b_len)))
            angle = abs(math.degrees(math.acos(cosv)))
            angle = min(angle, 180.0 - angle)
            if angle <= max_angle_deg and line_a.distance(line_b) <= max_dist:
                return True
    return False


def evaluate(input_gdf: Any, skeleton_gdf: Any, thresholds: Dict[str, Any]) -> Dict[str, Any]:
    polygon = input_gdf.unary_union
    lines = _line_strings(skeleton_gdf)
    graph = build_graph(lines)

    base_length = float(polygon.length)
    skeleton_length = float(sum(line.length for line in lines))
    length_change_rate = 0.0 if base_length == 0 else abs(skeleton_length - base_length) / base_length

    metrics = {
        "component_count": nx.number_connected_components(graph) if graph.number_of_nodes() else 0,
        "leaf_count": sum(1 for _, degree in graph.degree() if degree == 1),
        "branch_count": sum(1 for _, degree in graph.degree() if degree >= 3),
        "total_length": skeleton_length,
        "length_change_rate": length_change_rate,
        "outside_ratio": outside_ratio(lines, polygon, float(thresholds.get("sample_step", 1.0))),
        "parallel_pair_found": has_parallel_pair(
            lines,
            max_dist=float(thresholds.get("parallel_max_dist", 2.0)),
            max_angle_deg=float(thresholds.get("parallel_max_angle_deg", 10.0)),
        ),
    }

    checks = {
        "max_components": metrics["component_count"] <= int(thresholds.get("max_components", 999999)),
        "min_leaf_count": metrics["leaf_count"] >= int(thresholds.get("min_leaf_count", 0)),
        "max_branch_count": metrics["branch_count"] <= int(thresholds.get("max_branch_count", 999999)),
        "max_length_change_rate": metrics["length_change_rate"] <= float(thresholds.get("max_length_change_rate", 1.0)),
        "max_outside_ratio": metrics["outside_ratio"] <= float(thresholds.get("max_outside_ratio", 1.0)),
        "parallel_pair_required": (not thresholds.get("require_parallel_pair", False)) or metrics["parallel_pair_found"],
    }

    return {"metrics": metrics, "checks": checks, "passed": all(checks.values())}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate skeleton quality metrics and pass/fail gates.")
    parser.add_argument("--input", required=True, help="Input polygon GeoJSON/GeoPackage path")
    parser.add_argument("--skeleton", required=True, help="Skeleton line GeoJSON/GeoPackage path")
    parser.add_argument("--thresholds", required=True, help="JSON file for threshold configuration")
    parser.add_argument("--output", required=False, help="Optional output JSON path")
    return parser.parse_args()


def main() -> int:
    if gpd is None:
        raise ModuleNotFoundError("geopandas is required to run the CLI entrypoint")
    args = parse_args()
    input_gdf = gpd.read_file(args.input)
    skeleton_gdf = gpd.read_file(args.skeleton)
    thresholds = json.loads(Path(args.thresholds).read_text(encoding="utf-8"))

    result = evaluate(input_gdf, skeleton_gdf, thresholds)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.output:
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
