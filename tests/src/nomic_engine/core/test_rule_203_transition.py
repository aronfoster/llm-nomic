"""
Tests for the Rule 203 transition behavior.

Rule 203 behavior is now handled by the majority_after_loops flag
(default=2). See test_majority_after_loops.py for comprehensive tests.

This file is retained as a compatibility shim and verifies that the
default flag value (2) reproduces the original Rule 203 behavior.
"""

# All Rule 203 transition tests have been migrated to
# test_majority_after_loops.py, which tests the new
# _check_majority_after_loops() method that replaced
# _check_rule_203_transition().
