"""Finding models shared by the PR validation check families."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Failure:
    rule_id: str
    file: str
    message: str
    line: int = 1
    severity: str = "error"
    remediation: str = ""
    docs: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "file": self.file,
            "line": self.line,
            "message": self.message,
            "severity": self.severity,
            "remediation": self.remediation,
            "docs": self.docs,
        }