"""视频制作核心能力：composition 编译与 HyperFrames 渲染。"""
from .composition_builder import CompositionSpecError, build_composition_html

__all__ = ["CompositionSpecError", "build_composition_html"]
