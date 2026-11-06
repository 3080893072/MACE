"""Render the current MACE pipeline as a clean flowchart.

The figure reflects the M13 state: deterministic AST + graph discovery (C0),
an optional Qwen semantic-proposal / one-correction feedback path, AST identity
mapping into U_graph / U_qwen / U_union, role-separated MSMS/MMBS causal
search, and verifier-only confirmation.  The HIDDEN reference is drawn outside
the loop and is never an input.

Usage
-----
python scripts/make_mace_flowchart.py
python scripts/make_mace_flowchart.py --lang zh
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

KIT = Path(__file__).resolve().parents[1]
OUT = KIT / "docs" / "figures"

INK = "#1F2937"
MUTED = "#4B5563"
FAINT = "#6B7280"
BLUE = "#2B6CB0"
BLUE_FILL = "#EAF2FB"
ORANGE = "#C05621"
ORANGE_FILL = "#FFF4E6"
GREEN = "#2F855A"
GREEN_FILL = "#E8F5EE"
RED = "#9B2C2C"
RED_FILL = "#FDF2F2"
SLATE_FILL = "#F3F4F6"
WHITE = "#FFFFFF"

TEXT: Dict[str, Dict[str, object]] = {
    "en": {
        "title": "MACE: Masking-Aware Contract Engine",
        "subtitle": ("Current pipeline (M13, 2026-11-04)  —  operation-level MSMS / MMBS "
                     "discovery with optional semantic hypotheses"),
        "input_title": "0 | INPUTS",
        "input_body": [
            "program P, marked operation A, finite legal domain D",
            "candidate operations from AST + graph: U_graph",
        ],
        "det_title": "1a | Deterministic discovery (C0)",
        "det_body": [
            "AST SourceIndex + graph edges",
            "executable statements -> U_graph",
            "no model call",
        ],
        "qwen_title": "1b | Optional semantic proposal",
        "qwen_body": [
            "Qwen 32B proposes MSMS / MMBS sets",
            "condition + source evidence + hypotheses",
            "status = HYPOTHESIS only",
        ],
        "map_title": "2 | AST identity mapping",
        "map_body": [
            "U_union = U_graph + U_qwen   (U_graph is never pruned)",
            "new executable statement -> U_qwen",
            "if / for / while / try / with / match -> control_context (never deletable)",
        ],
        "search_title": "3 | Role-separated causal search (real P+ / P- execution)",
        "msms_title": "MSMS  (masked side)",
        "msms_body": [
            "queue: kept set S",
            "evaluate D = U - S",
            "minimal nonempty S with Masked(D)",
        ],
        "mmbs_title": "MMBS  (exposed side)",
        "mmbs_body": [
            "queue: disabled set H",
            "evaluate D = H",
            "minimal nonempty D with Exposed(D)",
        ],
        "search_footer": ("shared EvidenceStore  ·  strict alternation  ·  probe budget  ·  "
                          "OK / UNKNOWN / INVALID  ·  UNKNOWN is never False"),
        "verify_title": "4 | Bounded verification (sole confirmer)",
        "verify_body": [
            "only_set_masks · disabling_set_exposes · proper-subset minimality",
            "condition exact / sound / complete on the pilot domain",
            "real v3: set-level confirmation; condition NOT_EVALUATED",
            "model output cannot promote itself",
        ],
        "feedback_title": "4b | Feedback (max 1)",
        "feedback_body": [
            "real failed input + arguments",
            "condition truth / set evidence",
            "stripped control / mapping errors",
        ],
        "out_title": "5 | OUTPUT",
        "out_body": [
            "confirmed MSMS / MMBS per input + conditions",
            "evidence: BOUNDED / TESTED / REFUTED / UNKNOWN — never PROVEN",
            "unconfirmed = UNKNOWN / NOT_EVALUATED, not False",
        ],
        "hidden_title": "HIDDEN reference / scorer",
        "hidden_body": [
            "evaluation only",
            "never enters prompts, search, or confirmation",
        ],
        "legend": [
            ("solid blue", "deterministic"),
            ("dashed orange", "optional Qwen"),
            ("green", "confirmed output"),
        ],
        "arrow_optional": "optional",
        "arrow_union": "U_union",
        "arrow_evidence": "evidence",
        "arrow_confirmed": "VERIFIED / SET_CONFIRMED",
        "arrow_failed": "not confirmed",
        "arrow_loop": "one correction; then re-run all verification",
        "arrow_loop_short": "feedback loop (max 1)",
    },
    "zh": {
        "title": "MACE：掩蔽感知契约引擎",
        "subtitle": "当前流水线（M13，2026-11-04）——操作级 MSMS / MMBS 发现 + 可选语义假设",
        "input_title": "0 | 输入",
        "input_body": [
            "程序 P、被标记操作 A、有限合法输入域 D",
            "AST + 图给出的候选操作：U_graph",
        ],
        "det_title": "1a | 确定性发现（C0）",
        "det_body": [
            "AST SourceIndex + 图边",
            "可执行语句 -> U_graph",
            "不调用模型",
        ],
        "qwen_title": "1b | 可选语义提议",
        "qwen_body": [
            "Qwen 32B 提出 MSMS / MMBS 集合",
            "条件 + 源码证据 + 待验证假设",
            "状态 = HYPOTHESIS（假设）",
        ],
        "map_title": "2 | AST 身份映射",
        "map_body": [
            "U_union = U_graph + U_qwen（不裁剪 U_graph）",
            "新可执行语句 -> U_qwen",
            "if / for / while / try / with / match -> 控制上下文（绝不可删除）",
        ],
        "search_title": "3 | 角色分离因果搜索（真实 P+ / P- 执行）",
        "msms_title": "MSMS（掩蔽侧）",
        "msms_body": [
            "队列：保留集合 S",
            "评估 D = U - S",
            "找最小非空 S，使 Masked(D)",
        ],
        "mmbs_title": "MMBS（暴露侧）",
        "mmbs_body": [
            "队列：禁用集合 H",
            "评估 D = H",
            "找最小非空 D，使 Exposed(D)",
        ],
        "search_footer": ("共享 EvidenceStore · 严格交替 · 探测预算 · "
                          "OK / UNKNOWN / INVALID · UNKNOWN 绝不当 False"),
        "verify_title": "4 | 有界验证（唯一确认者）",
        "verify_body": [
            "only_set_masks · disabling_set_exposes · 真子集最小性",
            "pilot 上条件 exact / sound / complete",
            "真实 v3 只做集合级确认；条件 NOT_EVALUATED",
            "模型输出不能自我提升为正确",
        ],
        "feedback_title": "4b | 反例反馈（最多 1 次）",
        "feedback_body": [
            "真实失败输入 + 参数",
            "条件真假 / 集合证据",
            "被剥离的控制 / 映射错误",
        ],
        "out_title": "5 | 输出",
        "out_body": [
            "逐输入确认的 MSMS / MMBS + 条件",
            "证据：BOUNDED / TESTED / REFUTED / UNKNOWN——绝不写 PROVEN",
            "未确认 = UNKNOWN / NOT_EVALUATED，不是 False",
        ],
        "hidden_title": "HIDDEN 参考答案 / scorer",
        "hidden_body": [
            "仅用于评估",
            "绝不进入提示词、搜索或确认",
        ],
        "legend": [
            ("蓝色实线", "确定性"),
            ("橙色虚线", "可选 Qwen"),
            ("绿色", "已确认输出"),
        ],
        "arrow_optional": "可选",
        "arrow_union": "U_union",
        "arrow_evidence": "证据",
        "arrow_confirmed": "VERIFIED / SET_CONFIRMED",
        "arrow_failed": "未确认",
        "arrow_loop": "最多修正一次；修正后必须重新完整核验",
        "arrow_loop_short": "反馈回路（最多 1 次）",
    },
}


def _font(lang: str) -> str:
    if lang == "zh":
        return "Microsoft YaHei"
    return "Arial"


def _box(ax, x: float, y: float, w: float, h: float, *,
         edge: str, fill: str, dashed: bool = False, lw: float = 1.5) -> None:
    patch = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.35,rounding_size=0.8",
        linewidth=lw, edgecolor=edge, facecolor=fill,
        linestyle=(0, (5, 3)) if dashed else "solid",
        mutation_aspect=1.0, zorder=2)
    ax.add_patch(patch)


def _text(ax, x: float, y: float, lines: Sequence[str], *,
          size: float = 9.2, color: str = INK, weight: str = "normal",
          ha: str = "left", va: str = "top", family: str = "Arial",
          spacing: float = 2.05, zorder: int = 5) -> None:
    for i, line in enumerate(lines):
        ax.text(x, y - i * spacing, line, fontsize=size, color=color,
                fontweight=weight, ha=ha, va=va, family=family, zorder=zorder)


def _title(ax, x: float, y: float, text: str, *,
           family: str, size: float = 10.6) -> None:
    ax.text(x, y, text, fontsize=size, color=INK, fontweight="bold",
            ha="left", va="top", family=family, zorder=6)


def _arrow(ax, start: Tuple[float, float], end: Tuple[float, float], *,
           color: str = MUTED, dashed: bool = False, lw: float = 1.5,
           rad: float = 0.0, mutation: float = 14) -> None:
    patch = FancyArrowPatch(
        start, end, arrowstyle="-|>", mutation_scale=mutation,
        linewidth=lw, color=color,
        linestyle=(0, (4, 3)) if dashed else "solid",
        connectionstyle=f"arc3,rad={rad}",
        shrinkA=2, shrinkB=2, zorder=3)
    ax.add_patch(patch)


def _label(ax, x: float, y: float, text: str, *, family: str,
           color: str = MUTED, size: float = 7.8, ha: str = "center",
           rotation: float = 0) -> None:
    ax.text(x, y, text, fontsize=size, color=color, ha=ha, va="center",
            family=family, rotation=rotation, zorder=7,
            bbox=dict(boxstyle="round,pad=0.18", facecolor=WHITE,
                      edgecolor="none", alpha=0.92))


def _legend(ax, x: float, y: float, entries: Sequence[Tuple[str, str]], *,
            family: str) -> None:
    colors = {"solid blue": BLUE, "dashed orange": ORANGE, "green": GREEN,
              "蓝色实线": BLUE, "橙色虚线": ORANGE, "绿色": GREEN}
    for i, (kind, meaning) in enumerate(entries):
        yy = y - i * 2.0
        c = colors[kind]
        ax.plot([x, x + 2.4], [yy, yy], color=c, lw=1.8,
                linestyle=(0, (4, 2)) if "dashed" in kind or "虚线" in kind else "solid",
                zorder=6)
        ax.text(x + 3.0, yy, f"{kind}: {meaning}", fontsize=7.8, color=FAINT,
                ha="left", va="center", family=family, zorder=6)


def draw(lang: str, out_png: Path, out_svg: Path, out_pdf: Path) -> None:
    t = TEXT[lang]
    family = _font(lang)

    plt.rcParams["font.family"] = family
    plt.rcParams["axes.unicode_minus"] = False

    fig = plt.figure(figsize=(16, 10.5), facecolor=WHITE)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 104)
    ax.set_ylim(0, 100)
    ax.axis("off")

    # Title
    ax.text(4, 97.3, str(t["title"]), fontsize=23, color=INK,
            fontweight="bold", ha="left", va="top", family=family)
    ax.text(4, 93.0, str(t["subtitle"]), fontsize=10.8, color=FAINT,
            ha="left", va="top", family=family)

    # 0 Input
    _box(ax, 28, 81.5, 44, 7.6, edge=BLUE, fill=BLUE_FILL)
    _title(ax, 30.5, 87.5, str(t["input_title"]), family=family)
    _text(ax, 30.5, 84.8, t["input_body"], size=9.0, family=family, spacing=2.0)

    # 1a Deterministic
    _box(ax, 3, 60.5, 34, 15.5, edge=BLUE, fill=BLUE_FILL)
    _title(ax, 5.5, 74.6, str(t["det_title"]), family=family)
    _text(ax, 5.5, 71.2, t["det_body"], size=9.0, family=family, spacing=2.5)

    # 1b Optional Qwen
    _box(ax, 63, 60.5, 34, 15.5, edge=ORANGE, fill=ORANGE_FILL, dashed=True)
    _title(ax, 65.5, 74.6, str(t["qwen_title"]), family=family)
    _text(ax, 65.5, 71.2, t["qwen_body"], size=9.0, family=family, spacing=2.5)

    # 2 Mapping
    _box(ax, 25, 44.5, 50, 10.8, edge=BLUE, fill=SLATE_FILL)
    _title(ax, 27.5, 54.0, str(t["map_title"]), family=family)
    _text(ax, 27.5, 51.0, t["map_body"], size=8.7, family=family, spacing=2.05)

    # 3 Search
    _box(ax, 5, 25.6, 90, 15.8, edge=GREEN, fill=GREEN_FILL)
    _title(ax, 7.5, 40.0, str(t["search_title"]), family=family)
    _box(ax, 8, 28.1, 40, 9.2, edge=GREEN, fill=WHITE)
    _title(ax, 10.2, 36.0, str(t["msms_title"]), family=family, size=9.8)
    _text(ax, 10.2, 33.6, t["msms_body"], size=8.6, family=family, spacing=1.65)
    _box(ax, 52, 28.1, 40, 9.2, edge=GREEN, fill=WHITE)
    _title(ax, 54.2, 36.0, str(t["mmbs_title"]), family=family, size=9.8)
    _text(ax, 54.2, 33.6, t["mmbs_body"], size=8.6, family=family, spacing=1.65)
    ax.text(50, 26.8, str(t["search_footer"]), fontsize=8.1, color=MUTED,
            ha="center", va="center", family=family, zorder=6)

    # 4 Verifier
    _box(ax, 13, 11.8, 62, 11.2, edge=GREEN, fill=WHITE)
    _title(ax, 15.5, 21.5, str(t["verify_title"]), family=family)
    _text(ax, 15.5, 18.8, t["verify_body"], size=8.5, family=family, spacing=1.85)

    # 4b Feedback
    _box(ax, 79, 11.8, 16.5, 11.2, edge=ORANGE, fill=ORANGE_FILL, dashed=True)
    _title(ax, 80.8, 21.5, str(t["feedback_title"]), family=family, size=9.2)
    _text(ax, 80.8, 18.8, t["feedback_body"], size=8.1, family=family, spacing=1.85)

    # 5 Output
    _box(ax, 24, 1.0, 52, 8.8, edge=GREEN, fill=GREEN_FILL)
    _title(ax, 26.5, 9.2, str(t["out_title"]), family=family)
    _text(ax, 26.5, 6.5, t["out_body"], size=8.4, family=family, spacing=1.85)

    # HIDDEN boundary
    _box(ax, 2, 1.0, 19.5, 8.8, edge=RED, fill=RED_FILL, dashed=True, lw=1.2)
    _title(ax, 4.0, 9.0, str(t["hidden_title"]), family=family, size=8.8)
    _text(ax, 4.0, 6.3, t["hidden_body"], size=7.6, family=family, spacing=1.75)

    # Legend
    _legend(ax, 79, 8.6, t["legend"], family=family)  # type: ignore[arg-type]

    # Arrows
    _arrow(ax, (36, 81.5), (20, 76.0), color=BLUE, lw=1.7)
    _arrow(ax, (64, 81.5), (80, 76.0), color=ORANGE, dashed=True, lw=1.7)
    _label(ax, 76.5, 80.0, str(t["arrow_optional"]), family=family, color=ORANGE)

    _arrow(ax, (20, 60.5), (40, 55.3), color=BLUE, lw=1.7)
    _arrow(ax, (80, 60.5), (60, 55.3), color=ORANGE, dashed=True, lw=1.7)

    _arrow(ax, (50, 44.5), (50, 41.4), color=BLUE, lw=1.7)
    _label(ax, 55.0, 42.9, str(t["arrow_union"]), family=family, color=BLUE)

    _arrow(ax, (50, 25.6), (44, 23.0), color=GREEN, lw=1.7)
    _label(ax, 55.0, 24.3, str(t["arrow_evidence"]), family=family, color=GREEN)

    _arrow(ax, (44, 11.8), (44, 9.8), color=GREEN, lw=1.9)
    _label(ax, 45.0, 10.8, str(t["arrow_confirmed"]), family=family,
           color=GREEN, size=7.4, ha="left")

    _arrow(ax, (75, 17.4), (79, 17.4), color=ORANGE, dashed=True, lw=1.5)
    _label(ax, 77.0, 19.2, str(t["arrow_failed"]), family=family,
           color=ORANGE, size=7.4)

    # Feedback loop, routed outside the main canvas so it never crosses a box.
    loop = [(95.5, 17.4), (101.6, 17.4), (101.6, 68.3), (97.2, 68.3)]
    xs, ys = zip(*loop)
    ax.plot(xs, ys, color=ORANGE, lw=1.5, linestyle=(0, (4, 3)), zorder=3)
    _arrow(ax, (101.6, 68.3), (97.2, 68.3), color=ORANGE, dashed=True, lw=1.5)
    _label(ax, 101.6, 50.0, str(t["arrow_loop_short"]), family=family,
           color=ORANGE, size=7.0, rotation=90)

    # A quiet divider between the main loop and HIDDEN.
    ax.plot([23.2, 23.2], [1.5, 10.2], color=RED, lw=0.8,
            linestyle=(0, (2, 3)), alpha=0.55, zorder=1)

    fig.savefig(out_png, dpi=300, facecolor=WHITE, bbox_inches="tight",
                pad_inches=0.18)
    fig.savefig(out_svg, facecolor=WHITE, bbox_inches="tight", pad_inches=0.18)
    fig.savefig(out_pdf, facecolor=WHITE, bbox_inches="tight", pad_inches=0.18)
    plt.close(fig)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", choices=("en", "zh", "both"), default="both")
    parser.add_argument("--outdir", type=Path, default=OUT)
    args = parser.parse_args(argv)
    args.outdir.mkdir(parents=True, exist_ok=True)
    jobs: List[Tuple[str, str]] = []
    if args.lang in ("en", "both"):
        jobs.append(("en", "mace_current_pipeline"))
    if args.lang in ("zh", "both"):
        jobs.append(("zh", "mace_current_pipeline_zh"))
    for lang, stem in jobs:
        png = args.outdir / f"{stem}.png"
        svg = args.outdir / f"{stem}.svg"
        pdf = args.outdir / f"{stem}.pdf"
        draw(lang, png, svg, pdf)
        print(f"wrote {png}")
        print(f"wrote {svg}")
        print(f"wrote {pdf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
