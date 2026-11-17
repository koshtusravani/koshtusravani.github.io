"""
Fetches public LeetCode statistics for one user and writes them to leetcode.json.

The script runs inside a scheduled GitHub Actions workflow. On any failure it exits
with an error and leaves the existing leetcode.json untouched, so the portfolio keeps
showing the last good snapshot.
"""

import datetime
import json
import pathlib
import sys
import urllib.request

USERNAME = "sravanikoshtu"
OUTPUT = pathlib.Path(__file__).resolve().parents[2] / "leetcode.json"
GRAPHQL_URL = "https://leetcode.com/graphql/"

QUERY = """
query userStats($username: String!) {
  allQuestionsCount { difficulty count }
  matchedUser(username: $username) {
    profile { ranking }
    submissionCalendar
    submitStats {
      acSubmissionNum { difficulty count submissions }
      totalSubmissionNum { difficulty count submissions }
    }
  }
}
"""


def fetch_stats(username):
    """Sends the GraphQL query and returns the decoded data object."""
    body = json.dumps({"query": QUERY, "variables": {"username": username}}).encode("utf-8")
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Referer": "https://leetcode.com/u/" + username + "/",
            "User-Agent": "Mozilla/5.0 (portfolio stats updater)",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("errors"):
        raise RuntimeError("GraphQL errors: " + json.dumps(payload["errors"]))
    data = payload.get("data") or {}
    if not data.get("matchedUser"):
        raise RuntimeError("User not found: " + username)
    return data


def by_difficulty(rows, field):
    """Maps difficulty names (All, Easy, Medium, Hard) to the requested numeric field."""
    return {row["difficulty"]: row.get(field, 0) for row in rows}


def build_snapshot(data):
    """Converts the raw GraphQL response into the flat format the portfolio reads."""
    user = data["matchedUser"]
    totals = by_difficulty(data["allQuestionsCount"], "count")
    solved = by_difficulty(user["submitStats"]["acSubmissionNum"], "count")
    accepted_subs = by_difficulty(user["submitStats"]["acSubmissionNum"], "submissions")
    all_subs = by_difficulty(user["submitStats"]["totalSubmissionNum"], "submissions")

    acceptance = None
    if all_subs.get("All"):
        acceptance = round(accepted_subs.get("All", 0) / all_subs["All"] * 100, 1)

    calendar = user.get("submissionCalendar") or "{}"
    if isinstance(calendar, str):
        calendar = json.loads(calendar)

    return {
        "username": USERNAME,
        "totalSolved": solved.get("All", 0),
        "totalQuestions": totals.get("All", 0),
        "easySolved": solved.get("Easy", 0),
        "totalEasy": totals.get("Easy", 0),
        "mediumSolved": solved.get("Medium", 0),
        "totalMedium": totals.get("Medium", 0),
        "hardSolved": solved.get("Hard", 0),
        "totalHard": totals.get("Hard", 0),
        "ranking": (user.get("profile") or {}).get("ranking"),
        "acceptanceRate": acceptance,
        "submissionCalendar": calendar,
        "updatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }


def main():
    try:
        snapshot = build_snapshot(fetch_stats(USERNAME))
    except Exception as error:  # noqa: BLE001
        print("LeetCode fetch failed, keeping the previous snapshot: " + str(error), file=sys.stderr)
        sys.exit(1)
    OUTPUT.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    print("Wrote " + str(OUTPUT) + " with " + str(snapshot["totalSolved"]) + " solved problems")


if __name__ == "__main__":
    main()