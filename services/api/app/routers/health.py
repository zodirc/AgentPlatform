from fastapi import APIRouter

router = APIRouter(tags=["health"])

# Registered in main.py at root paths /health/*
