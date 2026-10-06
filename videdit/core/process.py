"""Helper to run the external tools without a shell."""

import subprocess

from .errors import ToolError


def run_tool(command, check=True):
    """
    Run a command given as argument list and return the completed process.
    Raises ToolError if the binary is missing or, with check, if it fails.
    """
    command = [str(part) for part in command]
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except FileNotFoundError:
        raise ToolError("'{}' was not found. Is it installed?".format(command[0])) from None
    if check and result.returncode != 0:
        raise ToolError("{} failed: {}".format(command[0], result.stderr.strip()))
    return result
