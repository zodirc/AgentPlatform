"""健康检查路由占位模块。

实际 ``/health/*`` 端点在 ``main.py`` 根路径注册；本模块仅声明 ``APIRouter`` 标签，
供 OpenAPI 分组与文档引用。
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])

# Registered in main.py at root paths /health/*
