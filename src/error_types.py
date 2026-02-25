"""Shared error taxonomy for resilient execution paths."""

from enum import Enum


class ErrorType(str, Enum):
    """Canonical error types used across agent/runtime/coordinator layers."""

    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    UPSTREAM_RATE_LIMIT = "UPSTREAM_RATE_LIMIT"
    SEARCH_FAILURE = "SEARCH_FAILURE"
    INTERNAL_FAILURE = "INTERNAL_FAILURE"
    PARSE_FAILURE = "PARSE_FAILURE"
    EMPTY_OUTPUT = "EMPTY_OUTPUT"
