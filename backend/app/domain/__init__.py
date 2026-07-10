"""Pure domain layer (specs/04, specs/06).

Layering rule (specs/03 §2): nothing in this package performs IO, reads
the clock, or draws randomness. Lineage refs are content-addressed so
identical inputs always produce identical refs (HR-5 replay).
"""
