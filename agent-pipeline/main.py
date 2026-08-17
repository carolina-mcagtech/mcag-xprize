"""
FloridaInspect Agent — CLI entry point.

Usage:
    python main.py --photos photo1.jpg photo2.jpg --address "123 Main St, Tampa FL 33601"
    python main.py --demo                   # run the built-in demo scenario
    python main.py --adk-web                # launch ADK web UI for interactive testing

Environment:
    Requires GEMINI_API_KEY in .env or environment.
    Copy .env.example to .env and fill in your key before running.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _check_env() -> None:
    """Abort early with a clear message if required environment variables are missing."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key or key == "your_key_here":
        print(
            "ERROR: GEMINI_API_KEY is not set or is still the placeholder.\n"
            "Edit .env and replace 'your_key_here' with your real Gemini API key, then re-run.\n"
            "Get a free key at: https://aistudio.google.com/app/apikey"
        )
        sys.exit(1)


def run_inspection(photo_paths: list[str], property_address: str, inspection_date: str | None = None) -> None:
    """Run the full inspection pipeline via the ADK orchestrator.

    Args:
        photo_paths: List of paths to inspection photos.
        property_address: Street address of the inspected property.
        inspection_date: ISO date string; defaults to today.
    """
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai.types import Content, Part

    from orchestrator.agent import root_agent

    session_service = InMemorySessionService()
    runner = Runner(
        agent=root_agent,
        app_name="floridainspect",
        session_service=session_service,
    )

    session = session_service.create_session(app_name="floridainspect", user_id="inspector")

    import json

    job_payload = json.dumps(
        {
            "photo_paths": photo_paths,
            "property_address": property_address,
            "inspection_date": inspection_date or __import__("datetime").date.today().isoformat(),
            "location_hints": [None] * len(photo_paths),
        },
        indent=2,
    )

    message = Content(role="user", parts=[Part(text=job_payload)])

    print(f"\nFloridaInspect Agent — Processing {len(photo_paths)} photo(s)")
    print(f"Property: {property_address}")
    print("=" * 60)

    for event in runner.run(user_id="inspector", session_id=session.id, new_message=message):
        if event.is_final_response():
            for part in event.content.parts:
                if part.text:
                    print(part.text)


def run_adk_web() -> None:
    """Launch the ADK web development UI for interactive agent testing."""
    import subprocess

    print("Launching ADK Web UI at http://localhost:8000 ...")
    print("Press Ctrl+C to stop.")
    subprocess.run(
        ["adk", "web"],
        cwd=Path(__file__).parent,
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="FloridaInspect Agent — AI-powered Florida home inspection system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--photos",
        nargs="+",
        metavar="PATH",
        help="Paths to inspection photos (JPEG, PNG, WEBP)",
    )
    parser.add_argument(
        "--address",
        default="123 Sample Street, Tampa, FL 33601",
        help="Property street address",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Inspection date (ISO format, e.g. 2024-03-15). Defaults to today.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run the built-in demo scenario from demo/run_demo.py",
    )
    parser.add_argument(
        "--adk-web",
        action="store_true",
        help="Launch the ADK web development UI",
    )

    args = parser.parse_args()

    if args.adk_web:
        _check_env()
        run_adk_web()
        return

    if args.demo:
        # Demo handles missing/placeholder key gracefully (offline mode)
        demo_path = Path(__file__).parent / "demo" / "run_demo.py"
        import runpy
        runpy.run_path(str(demo_path), run_name="__main__")
        return

    if not args.photos:
        parser.error("Provide --photos PATH [PATH ...] or use --demo / --adk-web")

    _check_env()
    run_inspection(
        photo_paths=args.photos,
        property_address=args.address,
        inspection_date=args.date,
    )


if __name__ == "__main__":
    main()
