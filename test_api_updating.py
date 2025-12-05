import requests
from datetime import datetime, timezone

def get_pbp_last_updated():
    url = "https://github.com/nflverse/nflverse-pbp/releases/latest"

    # GitHub redirects, so allow it
    response = requests.get(url, allow_redirects=True)

    # Extract the actual tag URL after redirects
    final_url = response.url

    # GitHub release URL structure:
    # https://github.com/nflverse/nflverse-pbp/releases/tag/<TAGNAME>
    tag = final_url.rstrip("/").split("/")[-1]

    print(f"Latest PBP release tag: {tag}")

    # Now query GitHub API for full release metadata
    api_url = f"https://api.github.com/repos/nflverse/nflverse-pbp/releases/tags/{tag}"
    data = requests.get(api_url).json()

    published_at = data.get("published_at")
    if not published_at:
        print("Could not read release timestamp.")
        return

    ts = datetime.fromisoformat(published_at.replace("Z", "+00:00"))

    print(f"Published at (UTC): {ts}")

    # Compare to current time
    now = datetime.now(timezone.utc)
    diff_min = (now - ts).total_seconds() / 60
    print(f"Updated {diff_min:.1f} minutes ago.")

    return diff_min


if __name__ == "__main__":
    diff = get_pbp_last_updated()

    if diff is None:
        print("No update information available.")
    elif diff < 15:
        print("PBP data is updating normally.")
    else:
        print("⚠️ PBP data appears delayed.")