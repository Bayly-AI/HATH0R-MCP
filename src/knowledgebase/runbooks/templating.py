"""Templating engine for runbook prompts.

Implements the original runbook substitution behavior:
- {env[key]} maps to values from env.yaml
- {var.name} maps to runtime-passed variables
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class TemplateEngine:
    """Runbook template engine."""

    @staticmethod
    def substitute_env(template: str, env_map: dict[str, Any]) -> str:
        """Replace {env[key]} patterns in the template with values from env_map."""
        if not env_map:
            return template
        for key, value in env_map.items():
            pattern = f"{{env[{key}]}}"
            template = template.replace(pattern, str(value))
        return template

    @staticmethod
    def substitute_vars(template: str, var_map: dict[str, str]) -> str:
        """Replace {var.name} patterns in the template with values from var_map."""
        if not var_map:
            return template
        for key, value in var_map.items():
            pattern = f"{{var.{key}}}"
            template = template.replace(pattern, str(value))
        return template

    @staticmethod
    def substitute(template: str, env_map: dict[str, Any], var_map: dict[str, str]) -> str:
        """Substitute both env and var patterns; vars applied after env to allow overriding."""
        # Apply env first, then variables
        after_env = TemplateEngine.substitute_env(template, env_map)
        return TemplateEngine.substitute_vars(after_env, var_map)
