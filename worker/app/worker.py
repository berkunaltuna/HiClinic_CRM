from __future__ import annotations

import os
import time


def main() -> None:
    version = os.getenv("APP_VERSION", "0.0.0")
    # Phase 0: worker is a stub. In later phases it will run the job queue.
    print(f"[worker] starting (version={version})")
    while True:
        print("[worker] alive")
        time.sleep(30)


if __name__ == "__main__":
    main()
