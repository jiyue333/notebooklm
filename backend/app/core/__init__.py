"""Core application primitives."""

from app.core.exceptions import AppError, register_exception_handlers

__all__ = ["AppError", "register_exception_handlers"]
