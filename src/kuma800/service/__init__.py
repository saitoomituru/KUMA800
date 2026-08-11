"""OS service manager向けadapter。"""

from .launchd import LaunchdPaths, render_launch_agents

__all__ = ["LaunchdPaths", "render_launch_agents"]
