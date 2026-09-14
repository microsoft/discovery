#!/usr/bin/env python3
"""
rules — modular validation rules for the Discovery catalog.

Each sibling module defines exactly one rule and exports it as ``RULE``.
``rules.registry`` discovers them automatically; nothing here needs editing
when a rule is added.
"""

from rules.base import Finding, PolicyConfig, Rule, RuleContext, Scope, Severity

__all__ = ["Finding", "PolicyConfig", "Rule", "RuleContext", "Scope", "Severity"]
