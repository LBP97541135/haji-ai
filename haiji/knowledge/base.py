"""
knowledge/base.py - knowledge 模块基础异常类

此文件保留，用于定义模块级别的基础异常和工具函数。
具体实现分布在：
  - definition.py：数据结构
  - chunker.py：TextChunker
  - embedder.py：BaseEmbedder / OpenAIEmbedder / MockEmbedder
  - store.py：InMemoryKnowledgeStore
  - loader.py：KnowledgeLoader
"""

from __future__ import annotations


class HaijiKnowledgeError(Exception):
    """knowledge 模块基础异常。"""
