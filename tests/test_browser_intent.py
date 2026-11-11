import unittest

from forgemind.browser_intent import browser_task_from_chat, is_web_task


class BrowserIntentTests(unittest.TestCase):
    def test_owner_screenshot_conversation(self):
        first = "alright make a dmv appointment for me here in Van Nuys for a transfer of title ownership of a car"
        self.assertEqual(browser_task_from_chat(first), first)
        history = [{"role": "user", "content": first},
                   {"role": "assistant", "content": "I cannot directly book appointments for the DMV..."}]
        task = browser_task_from_chat("no just use my browser and make the appointment", history)
        self.assertTrue(task.startswith(first))
        self.assertIn("use my browser", task)

    def test_website_tasks_are_recognized(self):
        for text in ["Book me a table for two at Bestia on Friday at 7",
                     "can you schedule an appointment with the Apple store genius bar",
                     "renew my car registration online for me",
                     "go to amazon.com and order more printer paper",
                     "browser: check my Mercury quote status",
                     "use my browser to fill out the contact form on davidsinsurance.org",
                     "please make a reservation at the Hilton in San Diego for Dec 3"]:
            self.assertIsNotNone(browser_task_from_chat(text), text)

    def test_ordinary_chat_and_questions_stay_chat(self):
        for text in ["How do I book a DMV appointment?",
                     "what documents do I need for a title transfer",
                     "I booked an appointment yesterday, remind me what to bring",
                     "don't book anything, just tell me the hours",
                     "open VYRA",
                     "write a poem about the ocean",
                     "Computer: organize my desktop",
                     ""]:
            self.assertIsNone(browser_task_from_chat(text), text)

    def test_prefix_always_wins(self):
        self.assertEqual(browser_task_from_chat("web: find the cheapest flight to Miami"), "find the cheapest flight to Miami")

    def test_follow_up_without_earlier_task_stays_as_is(self):
        self.assertEqual(browser_task_from_chat("use my browser and do it", []), "use my browser and do it")
        self.assertTrue(is_web_task("use my browser and do it"))


if __name__ == "__main__":
    unittest.main()
