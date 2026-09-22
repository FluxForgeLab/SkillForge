"""Shared domain enumerations."""

from __future__ import annotations

from enum import StrEnum


class KnowledgeUnitType(StrEnum):
    PROCEDURE = "procedure"
    DIAGNOSTIC_RULE = "diagnostic_rule"
    CONSTRAINT = "constraint"
    TOOL_INSTRUCTION = "tool_instruction"
    SUCCESS_CRITERION = "success_criterion"
    FAILURE_PATTERN = "failure_pattern"
    DEPENDENCY = "dependency"
    PERMISSION = "permission"


class FailureClass(StrEnum):
    MISSING_INSTRUCTION = "missing_instruction"
    WRONG_INSTRUCTION = "wrong_instruction"
    AMBIGUOUS_TRIGGER = "ambiguous_trigger"
    MISSING_TOOL = "missing_tool"
    TOOL_ERROR = "tool_error"
    PERMISSION_ERROR = "permission_error"
    ENVIRONMENT_ERROR = "environment_error"
    MODEL_REASONING_ERROR = "model_reasoning_error"
    VERIFICATION_GAP = "verification_gap"
    SOURCE_CONFLICT = "source_conflict"


class TraceEventType(StrEnum):
    WORKFLOW_STARTED = "workflow_started"
    MODEL_REQUEST = "model_request"
    MODEL_RESPONSE = "model_response"
    SKILL_GENERATED = "skill_generated"
    VALIDATION_RESULT = "validation_result"
    SANDBOX_CREATED = "sandbox_created"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    POLICY_VIOLATION = "policy_violation"
    ASSERTION = "assertion"
    FAILURE_DETECTED = "failure_detected"
    PATCH_GENERATED = "patch_generated"
    EVALUATION_COMPLETED = "evaluation_completed"
    VERSION_PROMOTED = "version_promoted"
    RETRIEVAL_QUERY = "retrieval_query"


class EvaluationRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
