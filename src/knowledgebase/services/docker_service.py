import subprocess
from typing import Any

def docker_execute(command: list[str], cwd: str | None = None) -> dict[str, Any]:
    """Execute a docker command securely."""
    try:
        # Prepend docker to command if not present
        if command[0] != "docker":
            command = ["docker"] + command
            
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

def docker_ps() -> dict[str, Any]:
    """List running docker containers."""
    return docker_execute(["docker", "ps"])

def docker_compose_up(service: str | None = None, detach: bool = True) -> dict[str, Any]:
    """Run docker-compose up."""
    cmd = ["docker", "compose", "up"]
    if detach:
        cmd.append("-d")
    if service:
        cmd.append(service)
    return docker_execute(cmd)
