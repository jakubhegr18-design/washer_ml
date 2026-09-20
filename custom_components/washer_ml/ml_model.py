"""Lightweight local ML models and fallback heuristics for Washer ML.

Everything here is pure Python with no third party ML dependencies so the
integration stays light enough to run on a Raspberry Pi next to Home
Assistant Core without loading heavy frameworks (no numpy, no TensorFlow).

Architecture:
  * Layer 1 - heuristic threshold classifier (works out of the box)
  * Layer 2 - decision tree (CART) trained from labelled cycles, stored as JSON
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Sequence

from .const import (
    CONF_IDLE_THRESHOLD,
    CONF_SPIN_THRESHOLD,
    DEFAULT_IDLE_THRESHOLD,
    DEFAULT_SPIN_THRESHOLD,
    FINISHED_IDLE_SECONDS,
    MODEL_DECISION_TREE,
    MODEL_LAYER_HEURISTIC,
    MODEL_LAYER_LEARNED,
    MODEL_SIMPLE_THRESHOLD,
    STATE_FINISHED,
    STATE_HEATING,
    STATE_OFF,
    STATE_RINSING,
    STATE_RUNNING,
    STATE_SPINNING,
    STATE_UNKNOWN,
    STATE_WASHING,
)

# Feature vector indices: [current_power, rolling_avg_1min, rolling_avg_5min,
#                          minutes_since_cycle_start, power_delta_from_previous_sample]
F_POWER = 0
F_AVG_60 = 1
F_AVG_300 = 2
F_MINUTES = 3
F_DELTA = 4

FEATURE_NAMES = (
    "current_power",
    "rolling_avg_1min",
    "rolling_avg_5min",
    "minutes_since_cycle_start",
    "power_delta_from_previous_sample",
)


def _rolling_mean_past(samples: Sequence[Sequence[float]], idx: int, seconds: float) -> float:
    """Mean of sample powers within ``seconds`` before ``idx`` (inclusive)."""
    if not samples:
        return 0.0
    target_ts = samples[idx][0]
    lo = target_ts - seconds
    total = 0.0
    count = 0
    for i in range(idx, -1, -1):
        ts, pw = samples[i]
        if ts < lo:
            break
        total += pw
        count += 1
    if count:
        return total / count
    return float(samples[idx][1])


def build_features(samples: Sequence[Sequence[float]], idx: int) -> list[float]:
    """Build the feature vector for sample ``idx`` (past data only)."""
    ts, power = samples[idx]
    prev_power = samples[idx - 1][1] if idx > 0 else 0.0
    minutes = (ts - samples[0][0]) / 60.0 if samples else 0.0
    return [
        round(float(power), 2),
        round(_rolling_mean_past(samples, idx, 60.0), 2),
        round(_rolling_mean_past(samples, idx, 300.0), 2),
        round(max(minutes, 0.0), 2),
        round(float(power) - float(prev_power), 2),
    ]


@dataclass(frozen=True)
class HeuristicConfig:
    """Thresholds used by the fallback classifier."""

    idle_threshold_w: float = DEFAULT_IDLE_THRESHOLD
    spin_threshold_w: float = DEFAULT_SPIN_THRESHOLD


class HeuristicClassifier:
    """Layer 1 - deterministic threshold rules.

    Runs from the moment the integration is installed, before any labelled
    cycle exists. All bounds are derived from the configured thresholds.
    """

    def __init__(self, config: HeuristicConfig | None = None) -> None:
        self._config = config or HeuristicConfig()

    def set_config(self, config: HeuristicConfig) -> None:
        self._config = config

    @property
    def config(self) -> HeuristicConfig:
        return self._config

    def predict(self, features: Sequence[float], has_spun: bool) -> tuple[str, float]:
        """Return (phase, confidence) for the given feature vector."""
        power = features[F_POWER]
        avg60 = features[F_AVG_60]
        minutes = features[F_MINUTES]
        cfg = self._config

        if power > cfg.spin_threshold_w:
            confidence = 90.0 + min(
                8.0, (power - cfg.spin_threshold_w) / cfg.spin_threshold_w * 8.0
            )
            return STATE_SPINNING, round(confidence, 1)

        if power >= cfg.idle_threshold_w:
            # Washing / heating band, usually spiky 60-165 W.
            if minutes < 12.0:
                # Heating dominates in the first part of the cycle.
                confidence = 76.0 + min(10.0, avg60 / 20.0)
                return STATE_HEATING, round(confidence, 1)
            if has_spun:
                # After a spin block the low-power bursts are rinsing.
                return STATE_RINSING, 74.0
            return STATE_WASHING, 78.0

        # Below idle threshold while a cycle is active -> sporadic rinsing bursts.
        if has_spun:
            return STATE_RINSING, 72.0
        return STATE_UNKNOWN, 50.0


def auto_label_cycle(
    raw_samples: Sequence[Sequence[float]], config: HeuristicConfig
) -> list[str]:
    """Attach a heuristic phase label to every sample of a finished cycle.

    Used to bootstrap training from imported/automatic cycles that never went
    through the manual calibration buttons.
    """
    labels: list[str] = []
    has_spun = False
    heur = HeuristicClassifier(config)
    for i in range(len(raw_samples)):
        feats = build_features(raw_samples, i)
        phase, _ = heur.predict(feats, has_spun)
        if phase == STATE_SPINNING:
            has_spun = True
        labels.append(phase)
    return labels


def segment_cycles(
    samples: Sequence[Sequence[float]], idle_threshold_w: float
) -> list[list[list[float]]]:
    """Split an ordered power timeline into individual wash cycles.

    A gap longer than ``FINISHED_IDLE_SECONDS`` below the idle threshold ends
    the current cycle definition.
    """
    cycles: list[list[list[float]]] = []
    current: list[list[float]] = []
    for ts, power in samples:
        if power > idle_threshold_w:
            if current and ts - current[-1][0] > FINISHED_IDLE_SECONDS:
                cycles.append(current)
                current = []
            current.append([ts, power])
        elif current:
            if ts - current[-1][0] > FINISHED_IDLE_SECONDS:
                cycles.append(current)
                current = []
            else:
                current.append([ts, power])
    if current:
        cycles.append(current)
    return cycles


def _nearest_marker(
    markers: Sequence[Sequence[Any]], ts: float
) -> str | None:
    """Nearest phase marker at or before ``ts``."""
    best: tuple[float, str] | None = None
    for marker in markers:
        marker_ts, phase = marker[0], marker[1]
        if marker_ts <= ts:
            if best is None or marker_ts > best[0]:
                best = (marker_ts, phase)
    return best[1] if best else None


def generate_training_samples(
    cycles: Sequence[dict[str, Any]],
) -> tuple[list[list[float]], list[str]]:
    """Assemble (features, labels) from stored cycles.

    The label for every sample is taken from the nearest *previous* manual
    calibration marker; cycles without markers fall back to their heuristic
    auto labels.
    """
    features_out: list[list[float]] = []
    labels_out: list[str] = []
    valid_labels = {
        STATE_RUNNING,
        STATE_HEATING,
        STATE_WASHING,
        STATE_RINSING,
        STATE_SPINNING,
        STATE_FINISHED,
    }
    for cycle in cycles:
        raw = cycle.get("raw_samples") or []
        if len(raw) < 10:
            continue
        markers = cycle.get("phase_labels") or []
        auto = cycle.get("auto_labels") or []
        if not markers and not auto:
            continue
        for i in range(len(raw)):
            label = _nearest_marker(markers, raw[i][0])
            if label is None and auto and i < len(auto):
                label = auto[i]
            if not label or label not in valid_labels:
                continue
            features_out.append(build_features(raw, i))
            labels_out.append(label)
    return features_out, labels_out


def _gini(counts: Counter[str]) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return 1.0 - sum((c / total) ** 2 for c in counts.values())


class _TreeNode:
    __slots__ = ("feature", "threshold", "left", "right", "counts")

    def __init__(self, counts: dict[str, int]) -> None:
        self.feature: int | None = None
        self.threshold: float | None = None
        self.left: _TreeNode | None = None
        self.right: _TreeNode | None = None
        self.counts = counts

    def to_dict(self) -> dict[str, Any]:
        if self.left is None:
            return {"counts": dict(self.counts)}
        return {
            "feature": self.feature,
            "threshold": self.threshold,
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "_TreeNode":
        node = cls(dict(data.get("counts", {})))
        if "left" in data:
            node.feature = data["feature"]
            node.threshold = data["threshold"]
            node.left = cls.from_dict(data["left"])
            node.right = cls.from_dict(data["right"])
        return node

    @property
    def label(self) -> str | None:
        if not self.counts:
            return None
        return max(self.counts, key=self.counts.get)


class DecisionTreeClassifier:
    """Small pure-Python CART decision tree (binary, gini based)."""

    def __init__(
        self,
        max_depth: int = 6,
        min_samples_leaf: int = 5,
        min_samples_split: int = 10,
    ) -> None:
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.min_samples_split = min_samples_split
        self.root: _TreeNode | None = None
        self.classes: list[str] = []

    def fit(self, samples: list[tuple[Sequence[float], str]]) -> None:
        labels = [label for _, label in samples]
        self.classes = sorted(set(labels))
        self.root = self._fit(samples, 0)
        if self.root is not None and self.root.left is None:
            cls = self.root.label
            self._single_class = cls
        else:
            self._single_class = None

    def _best_split(
        self, samples: list[tuple[Sequence[float], str]]
    ) -> tuple[int, float] | None:
        n = len(samples)
        if n < self.min_samples_split:
            return None
        labels = [s[1] for s in samples]
        cur_gini = _gini(Counter(labels))
        best_gain = 0.0
        best: tuple[int, float] | None = None
        n_features = len(samples[0][0])
        for f in range(n_features):
            order = sorted(range(n), key=lambda i: samples[i][0][f])
            counts_left: Counter[str] = Counter()
            counts_right = Counter(labels)
            prev_val: float | None = None
            for pos, i in enumerate(order):
                label = samples[i][1]
                val = samples[i][0][f]
                counts_left[label] += 1
                counts_right[label] -= 1
                left_n = pos + 1
                right_n = n - left_n
                if left_n < self.min_samples_leaf or right_n < self.min_samples_leaf:
                    prev_val = val
                    continue
                if prev_val is not None and val > prev_val:
                    threshold = (prev_val + val) / 2.0
                    gini_l = _gini(counts_left)
                    gini_r = _gini(counts_right)
                    gain = cur_gini - (
                        left_n / n * gini_l + right_n / n * gini_r
                    )
                    if gain > best_gain + 1e-9:
                        best_gain = gain
                        best = (f, threshold)
                prev_val = val
        return best

    def _fit(
        self, samples: list[tuple[Sequence[float], str]], depth: int
    ) -> _TreeNode:
        counts = dict(Counter(label for _, label in samples))
        if depth >= self.max_depth or len(samples) < self.min_samples_split:
            return _TreeNode(counts)
        split = self._best_split(samples)
        if split is None:
            return _TreeNode(counts)
        f, threshold = split
        left = [s for s in samples if s[0][f] <= threshold]
        right = [s for s in samples if s[0][f] > threshold]
        if not left or not right:
            return _TreeNode(counts)
        node = _TreeNode(counts)
        node.feature = f
        node.threshold = threshold
        node.left = self._fit(left, depth + 1)
        node.right = self._fit(right, depth + 1)
        return node

    def predict_proba(self, features: Sequence[float]) -> dict[str, float]:
        if self.root is None:
            raise RuntimeError("Tree is not trained")
        node = self.root
        while node.left is not None and node.feature is not None:
            if features[node.feature] <= (node.threshold or 0.0):
                node = node.left
            else:
                node = node.right
        total = sum(node.counts.values())
        n_classes = len(self.classes)
        out: dict[str, float] = {}
        for cls in self.classes:
            cnt = node.counts.get(cls, 0)
            out[cls] = (cnt + 1.0) / (total + n_classes)
        return out

    def predict(self, features: Sequence[float]) -> tuple[str, float, dict[str, float]]:
        probs = self.predict_proba(features)
        phase = max(probs, key=probs.get)
        return phase, round(probs[phase] * 100.0, 1), probs

    def to_dict(self) -> dict[str, Any]:
        if self.root is None:
            raise RuntimeError("Tree is not trained")
        return {"classes": self.classes, "tree": self.root.to_dict()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecisionTreeClassifier":
        tree = cls()
        tree.classes = data.get("classes", [])
        tree.root = _TreeNode.from_dict(data["tree"])
        return tree


def train_decision_tree(
    features: Sequence[Sequence[float]],
    labels: Sequence[str],
    max_depth: int = 6,
    min_samples_leaf: int = 5,
) -> DecisionTreeClassifier:
    tree = DecisionTreeClassifier(
        max_depth=max_depth, min_samples_leaf=min_samples_leaf
    )
    tree.fit([(list(f), label) for f, label in zip(features, labels)])
    return tree


class WasherModel:
    """Two-layer detector: heuristic until a decision tree is trained."""

    def __init__(self, options: dict[str, Any]) -> None:
        self.options = options
        self._tree: DecisionTreeClassifier | None = None
        self._heuristic = HeuristicClassifier(HeuristicConfig())
        self._recreate_heuristic()

    def _recreate_heuristic(self) -> None:
        self._heuristic.set_config(
            HeuristicConfig(
                idle_threshold_w=float(
                    self.options.get(CONF_IDLE_THRESHOLD, DEFAULT_IDLE_THRESHOLD)
                ),
                spin_threshold_w=float(
                    self.options.get(CONF_SPIN_THRESHOLD, DEFAULT_SPIN_THRESHOLD)
                ),
            )
        )

    def reload_from(self, options: dict[str, Any]) -> None:
        self.options = options
        self._recreate_heuristic()

    def set_tree(self, tree: DecisionTreeClassifier | None) -> None:
        self._tree = tree

    @property
    def trained(self) -> bool:
        return self._tree is not None

    def predict(
        self, features: Sequence[float], has_spun: bool
    ) -> tuple[str, float, dict[str, float], str]:
        """Return (phase, confidence, per-class scores, active layer)."""
        if self.options.get("model_type") == MODEL_DECISION_TREE and self._tree is not None:
            phase, confidence, scores = self._tree.predict(features)
            return phase, confidence, scores, MODEL_LAYER_LEARNED
        phase, confidence = self._heuristic.predict(features, has_spun)
        scores: dict[str, float] = {state: 0.0 for state in self.supported_states}
        scores[phase] = round(confidence / 100.0, 4)
        return phase, confidence, scores, MODEL_LAYER_HEURISTIC

    @property
    def supported_states(self) -> tuple[str, ...]:
        return (
            STATE_RUNNING,
            STATE_HEATING,
            STATE_WASHING,
            STATE_RINSING,
            STATE_SPINNING,
            STATE_FINISHED,
            STATE_OFF,
            STATE_UNKNOWN,
        )

    def to_json_file(self, path: Any) -> None:
        """Write the trained tree to ``path`` (run in executor)."""
        data: dict[str, Any] = {}
        if self._tree is not None:
            data["tree"] = self._tree.to_dict()
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)

    def load_json_file(self, path: Any) -> bool:
        """Load a trained tree from ``path`` (run in executor)."""
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return False
        tree_data = data.get("tree")
        if not tree_data:
            return False
        self._tree = DecisionTreeClassifier.from_dict(tree_data)
        return True