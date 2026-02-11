def generate_feedback(submission_text: str, rubric: dict) -> dict:
    """
    Central feedback pipeline.
    Later this function will call an LLM.
    For now, returns structured mock feedback.
    """

    criteria = rubric.get("criteria", [])

    breakdown = []
    for c in criteria:
        breakdown.append({
            "criterion": c["name"],
            "score": 3,
            "strengths": f"The work demonstrates some understanding of {c['name'].lower()}.",
            "improvements": f"Consider expanding on ideas related to {c['name'].lower()}.",
            "evidence": submission_text[:120] + "..."
        })

    return {
        "overall_summary": "This is a solid draft that meets several rubric criteria. With more detail and refinement, it could be improved further.",
        "rubric_breakdown": breakdown,
        "next_steps": [
            "Review the rubric criteria and focus on one area to improve.",
            "Add more examples to support your ideas.",
            "Revise the structure for clarity."
        ]
    }
