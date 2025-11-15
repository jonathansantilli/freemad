from freemad import build_generation_prompt, build_critique_prompt


def test_generation_prompt_has_strict_sections():
    p = build_generation_prompt("Do X")
    # Order and presence
    assert p.index("SOLUTION:") < p.index("REASONING:")
    # Self-descriptive hints
    assert "STRICT OUTPUT FORMAT" in p


def test_critique_prompt_has_required_markers_and_rules():
    p = build_critique_prompt("Do X", own_solution="S1", peer_solutions=["P1", "P2"])
    # Presence
    assert "DECISION:" in p
    assert "REASONING:" in p
    assert "REVISED_SOLUTION:" in p
    # Self-descriptive hints
    assert "STRICT OUTPUT FORMAT" in p
    # Peer numbering guidance
    assert "Peer #1" in p and "Peer #2" in p

