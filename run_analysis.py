from datetime import datetime, timezone


def main():
    print("=" * 60)
    print("FOOTBALL ANALYSIS ENGINE")
    print("=" * 60)

    print(f"Run started: {datetime.now(timezone.utc).isoformat()}")
    print("System status: READY")
    print("Pipeline status: NOT STARTED")

    print("=" * 60)


if __name__ == "__main__":
    main()
