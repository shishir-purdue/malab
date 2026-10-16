"""Execute the tests stored in the notebook, using only Python's standard library.

No hardware notebook or live instrument is opened by this runner.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import traceback


def main():
    repo = Path(__file__).resolve().parents[1]
    path = repo / "notebooks" / "driver_offline_tests.ipynb"
    notebook = json.loads(path.read_text(encoding="utf-8"))
    os.chdir(repo.parent)
    namespace = {"__name__": "__main__"}
    count = 0
    failed = False
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] != "code":
            continue
        count += 1
        cell["execution_count"] = count
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                exec(compile("".join(cell["source"]), f"{path}:cell-{index}", "exec"), namespace)
        except Exception as exc:
            failed = True
            cell["outputs"] = [{"output_type": "error", "ename": type(exc).__name__,
                                "evalue": str(exc), "traceback": traceback.format_exc().splitlines()}]
            traceback.print_exc()
        else:
            cell["outputs"] = []
        if output.getvalue():
            cell["outputs"].insert(0, {"output_type": "stream", "name": "stdout", "text": output.getvalue()})
        print(f"{'FAIL' if failed else 'PASS'} notebook code cell {index}")
        if failed:
            break
    destination = repo / "notebooks" / "results" / "driver_offline_tests.executed.ipynb"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(notebook, indent=1) + "\n", encoding="utf-8")
    print(f"Executed {count} code cells (setup + tests). Results: {destination}")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
