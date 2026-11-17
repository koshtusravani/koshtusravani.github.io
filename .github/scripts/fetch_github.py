"""
Fetches public GitHub statistics for one user and writes them to github.json.

The script runs inside a scheduled GitHub Actions workflow and authenticates with the
workflow token. On any failure it exits with an error and leaves the existing
github.json untouched, so the portfolio keeps showing the last good snapshot.
"""

import datetime
import json
import os
import pathlib
import sys
import urllib.request

USERNAME = "koshtusravani"
OUTPUT = pathlib.Path(__file__).resolve().parents[2] / "github.json"
GRAPHQL_URL = "https://api.github.com/graphql"
TOP_LANGUAGES = 6

QUERY = """
query userStats($login: String!) {
  user(login: $login) {
    followers { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100) {
      totalCount
      nodes {
        stargazerCount
        forkCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def fetch_stats(login, token):
    """Sends the GraphQL query with the workflow token and returns the user object."""
    body = json.dumps({"query": QUERY, "variables": {"login": login}}).encode("utf-8")
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        headers={
            "Authorization": "bearer " + token,
            "Content-Type": "application/json",
            "User-Agent": "portfolio-stats-updater",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("errors"):
        raise RuntimeError("GraphQL errors: " + json.dumps(payload["errors"]))
    user = (payload.get("data") or {}).get("user")
    if not user:
        raise RuntimeError("User not found: " + login)
    return user


def compute_streaks(calendar):
    """Returns the current and longest daily contribution streaks from a date to count map."""
    days = sorted(calendar.items())
    longest = running = 0
    for _, count in days:
        running = running + 1 if count > 0 else 0
        longest = max(longest, running)

    current = 0
    index = len(days) - 1
    # A day with no contributions yet today does not break the current streak.
    if index >= 0 and days[index][1] == 0:
        index -= 1
    while index >= 0 and days[index][1] > 0:
        current += 1
        index -= 1
    return current, longest


def build_snapshot(user):
    """Converts the raw GraphQL user object into the flat format the portfolio reads."""
    repos = user["repositories"]["nodes"]
    language_sizes = {}
    language_colors = {}
    for repo in repos:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            language_sizes[name] = language_sizes.get(name, 0) + edge["size"]
            language_colors[name] = edge["node"]["color"] or "#8b95a7"

    total_size = sum(language_sizes.values()) or 1
    ranked = sorted(language_sizes.items(), key=lambda item: item[1], reverse=True)[:TOP_LANGUAGES]
    languages = [
        {"name": name, "color": language_colors[name], "percent": round(size / total_size * 100, 1)}
        for name, size in ranked
    ]

    contributions = user["contributionsCollection"]
    calendar = {}
    for week in contributions["contributionCalendar"]["weeks"]:
        for day in week["contributionDays"]:
            calendar[day["date"]] = day["contributionCount"]
    current_streak, longest_streak = compute_streaks(calendar)

    return {
        "username": USERNAME,
        "publicRepos": user["repositories"]["totalCount"],
        "followers": user["followers"]["totalCount"],
        "totalStars": sum(repo["stargazerCount"] for repo in repos),
        "totalForks": sum(repo["forkCount"] for repo in repos),
        "contributionsLastYear": contributions["contributionCalendar"]["totalContributions"],
        "commits": contributions["totalCommitContributions"],
        "pullRequests": contributions["totalPullRequestContributions"],
        "issues": contributions["totalIssueContributions"],
        "privateContributions": contributions["restrictedContributionsCount"],
        "currentStreak": current_streak,
        "longestStreak": longest_streak,
        "languages": languages,
        "calendar": calendar,
        "updatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }


def main():
    token = os.environ.get("GH_TOKEN")
    if not token:
        print("GH_TOKEN is not set", file=sys.stderr)
        sys.exit(1)
    try:
        snapshot = build_snapshot(fetch_stats(USERNAME, token))
    except Exception as error:  # noqa: BLE001
        print("GitHub fetch failed, keeping the previous snapshot: " + str(error), file=sys.stderr)
        sys.exit(1)
    OUTPUT.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    print("Wrote " + str(OUTPUT) + " with " + str(snapshot["contributionsLastYear"]) + " contributions")


if __name__ == "__main__":
    main()