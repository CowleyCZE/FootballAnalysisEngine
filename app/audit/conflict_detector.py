"""Audit používá jedinou implementaci ConflictDetector z research vrstvy (TODO 4.3).

`ConflictDetector.detect_conflicts(claims)` (dicty z DB -> nálezy auditu) a
`ConflictDetector().detect_and_resolve(claims)` (objekty Claim) sdílejí množinu
exkluzivních predikátů i klíč (subjekt, predikát).
"""
from app.research.conflict_detector import ConflictDetector, EXCLUSIVE_PREDICATES

__all__ = ["ConflictDetector", "EXCLUSIVE_PREDICATES"]
