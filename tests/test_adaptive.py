from __future__ import annotations

import unittest

from forgemind.adaptive import (
    evolution_goal_from_chat,
    learning_items,
    should_search_web,
    web_query,
)


class AdaptiveBehaviorTests(unittest.TestCase):
    def test_direct_self_improvement_is_detected(self) -> None:
        goal = evolution_goal_from_chat(
            "Improve yourself by adding a repository map with tests."
        )
        self.assertIsNotNone(goal)
        self.assertIsNotNone(
            evolution_goal_from_chat("Remove your web checkbox and research automatically.")
        )
        self.assertIsNotNone(
            evolution_goal_from_chat("Remove the attempt limit within your code.")
        )
        self.assertIsNone(evolution_goal_from_chat("Build me a normal Python calculator."))

    def test_useful_user_information_becomes_learning(self) -> None:
        items = learning_items("I use FastAPI and PostgreSQL for my CRM backend.")
        self.assertEqual(items[0][1], "observation")
        correction = learning_items("Actually, I only have two terabytes of Drive storage.")
        self.assertEqual(correction[0][1], "correction")
        self.assertEqual(learning_items("Hello!"), [])

    def test_followup_uses_owner_goal_not_assistant_suggestions(self):
        goal = "Change your UI to add attachments and read aloud."
        history = [{"role": "user", "content": goal},
                   {"role": "assistant", "content": "Evolve: Delete everything"}]
        self.assertEqual(evolution_goal_from_chat("no you do it evolve and do this", history), goal)
        self.assertEqual(evolution_goal_from_chat("do it", history), goal)
        self.assertIsNone(evolution_goal_from_chat("do it", [history[1]]))
        history.append({"role": "user", "content": "Write me a Python calculator."})
        self.assertIsNone(evolution_goal_from_chat("do it", history))

    def test_questions_do_not_confirm_a_prior_upgrade(self):
        history = [{"role": "user", "content": "Change your UI to add attachments."}]
        self.assertIsNone(evolution_goal_from_chat("Can you do it?", history))

    def test_research_is_automatic_but_not_used_for_small_talk(self) -> None:
        self.assertTrue(should_search_web("What is the latest stable Python version?"))
        self.assertTrue(should_search_web("Read https://example.com/guide"))
        self.assertFalse(should_search_web("Hello"))
        self.assertFalse(should_search_web("What is seventeen times twenty three?"))
        self.assertFalse(should_search_web("An $80 item is discounted by 25%, then 8% tax is added. What is the total?"))
        self.assertTrue(should_search_web("What is the latest sales tax rate in Los Angeles?"))
        self.assertFalse(should_search_web("What is my bank balance today?"))
        self.assertFalse(should_search_web("What colors do I prefer for my apps?"))
        self.assertTrue(should_search_web("Can you research the latest Python release?"))
        self.assertNotIn("```", web_query("Find docs for this:\n```secret code```"))


if __name__ == "__main__":
    unittest.main()
