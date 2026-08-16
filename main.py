"""Local SafeOps application entry point."""

import uvicorn


def main() -> None:
    """Run the development server using the active Python environment."""
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
