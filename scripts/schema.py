"""
schema.py — Change candidate schema constants for Phase 2 diff output.

Each change candidate represents a single detected difference between old/new DOCX versions.
"""

# Required fields for every change candidate
CHANGE_CANDIDATE_FIELDS = [
    "section_path",     # "5. Treatments > 5.1. Identity of IP"
    "object_type",      # "text" | "table" | "image" | "header_footer"
    "change_type",      # "add" | "delete" | "modify" | "move"
    "location_hint",    # "paragraph_idx=17" | "row=3,col=2" | "image2.png" | "header6.xml"
    "before",           # Previous version text/value (empty for add)
    "after",            # New version text/value (empty for delete)
    "evidence",         # Diff details (patch string, hashes, etc.)
    "move_from",        # Original location for move type (None otherwise)
    "move_to",          # New location for move type (None otherwise)
    "confidence",       # 0~1 (hash=1.0, fuzzy<1.0)
]

OBJECT_TYPES = {"text", "table", "image", "header_footer"}
CHANGE_TYPES = {"add", "delete", "modify", "move"}


def make_candidate(
    section_path: str,
    object_type: str,
    change_type: str,
    location_hint: str,
    before: str = "",
    after: str = "",
    evidence: str = "",
    move_from: str = None,
    move_to: str = None,
    confidence: float = 1.0,
) -> dict:
    """Create a validated change candidate dict."""
    return {
        "section_path": section_path,
        "object_type": object_type,
        "change_type": change_type,
        "location_hint": location_hint,
        "before": before,
        "after": after,
        "evidence": evidence,
        "move_from": move_from,
        "move_to": move_to,
        "confidence": confidence,
    }
