"""(v0.3.0 작업 중 임시 stub — Commit 7 에서 hooks/hooks.json 의 Stop entry 가
scripts/refresh.py 로 변경되며 이 파일은 삭제 예정).

Commit 7 까지는 hooks/hooks.json 의 Stop entry 가 아직 이 파일을 가리키므로
runtime 안전을 위해 minimal stub 유지.
"""
import sys


def main() -> int:
    return 0


if __name__ == "__main__":
    sys.exit(main())
