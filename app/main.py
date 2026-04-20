from app.coordinator import Coordinator
from config.settings import load_settings


def main() -> int:
    settings = load_settings()
    coordinator = Coordinator(settings)
    coordinator.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
