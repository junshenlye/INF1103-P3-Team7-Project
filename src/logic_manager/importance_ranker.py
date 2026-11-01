"""Global comparable ranking occurs before schedule appearances are copied."""


class ImportanceRanker:
    def rank(self, items):
        """Rank every comparable assessment and derive relative display bands.

        Ranking covers scheduled and unscheduled items together. Equal scores share
        the same rank and priority. Priority uses the item's relative position among
        the distinct observed scores, so it adapts to any number of input modules
        instead of relying on fixed score thresholds.
        """
        ranked_items = sorted(
            (item for item in items if item["importance_score"] is not None),
            key=lambda item: (
                -item["importance_score"],
                item["module_title"].casefold(),
                item["name"].casefold(),
                item["assessment_id"],
            ),
        )
        distinct_scores = sorted(
            {item["importance_score"] for item in ranked_items}, reverse=True
        )
        priority_by_score = {}
        for position, score in enumerate(distinct_scores):
            relative_position = (position + 0.5) / len(distinct_scores)
            if relative_position < 1 / 3:
                priority = "high"
            elif relative_position < 2 / 3:
                priority = "medium"
            else:
                priority = "low"
            priority_by_score[score] = priority
        previous_score = None
        current_rank = 0
        for position, item in enumerate(ranked_items, start=1):
            score = item["importance_score"]
            if score != previous_score:
                current_rank = position
                previous_score = score
            item["importance_rank"] = current_rank
            item["importance_ranked_count"] = len(ranked_items)
            item["priority"] = priority_by_score[score]
        return {
            "formula": "credit * weight_percent / 100",
            "ranking_scope": "all assessments with explicit module-level weights",
            "priority_method": "relative thirds of distinct observed scores",
            "ranked_assessment_count": len(ranked_items),
        }
