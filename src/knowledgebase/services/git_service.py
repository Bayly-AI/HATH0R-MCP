import subprocess
from typing import Any

def git_execute(command: list[str], cwd: str | None = None) -> dict[str, Any]:
    """Execute a git command securely."""
    try:
        if command[0] != "git":
            command = ["git"] + command
            
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def git_status(cwd: str | None = None) -> dict[str, Any]:
    """Get git status."""
    return git_execute(["git", "status"], cwd=cwd)

def git_log(n: int = 10, cwd: str | None = None) -> dict[str, Any]:
    """Get git log."""
    return git_execute(["git", "log", f"-n{n}", "--oneline"], cwd=cwd)

def git_diff(cwd: str | None = None) -> dict[str, Any]:
    """Get git diff."""
    return git_execute(["git", "diff"], cwd=cwd)
