"""The cold open: legacy Rebookr during the storm. Hit the red button and watch."""
import time

from legacy.faq import answer_faq
from legacy.rebooking import rebook

PASSENGERS = [
    (rebook, "My flight KRS to OSL tonight was cancelled. Can you rebook me?"),
    (answer_faq, "How many bags can I bring?"),
    (rebook, "Cancelled again!! I need to get home to BGO from OSL."),
    (answer_faq, "Will I get compensation?"),
]

if __name__ == "__main__":
    print("\033[33m\033[1m⛈  Rebookr v1 - storm traffic incoming...\033[0m")
    n = 0
    while True:
        for handler, text in PASSENGERS:
            n += 1
            print(f"\n\033[1mPassenger #{n}:\033[0m {text}")
            print(f"\033[1mRebookr:\033[0m {handler(text)}")   # no try/except. What could go wrong?
            time.sleep(2)
