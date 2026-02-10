"""
Template generation module.

Handles creation of Confluence content templates using the legacy REST API.
Templates are simpler than other content types — just creation, no versions,
labels, properties, or restrictions.
"""

import asyncio
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .base import ConfluenceAPIClient

if TYPE_CHECKING:
    from .checkpoint import CheckpointManager


class TemplateGenerator(ConfluenceAPIClient):
    """Generates Confluence content templates."""

    _TEMPLATE_TYPES = ["page", "blogpost"]

    def __init__(
        self,
        confluence_url: str,
        email: str,
        api_token: str,
        prefix: str,
        dry_run: bool = False,
        concurrency: int = 5,
        benchmark: Any | None = None,
        request_delay: float = 0.0,
        checkpoint: "CheckpointManager | None" = None,
    ):
        super().__init__(
            confluence_url,
            email,
            api_token,
            dry_run,
            concurrency,
            benchmark,
            request_delay,
        )
        self.prefix = prefix
        self.checkpoint = checkpoint
        self.run_id = f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        # Track created items
        self.created_templates: list[dict[str, str]] = []

    def set_run_id(self, run_id: str) -> None:
        """Set the run ID (should match the main generator's run ID)."""
        self.run_id = run_id

    # ========== TEMPLATE OPERATIONS ==========

    def create_template(
        self,
        space_key: str,
        index: int,
    ) -> dict[str, str] | None:
        """Create a single content template.

        Args:
            space_key: Space key to create the template in
            index: Template index (used for naming and type alternation)

        Returns:
            Dict with 'templateId', 'name', 'spaceKey' or None on failure
        """
        name = f"{self.prefix} Template {index + 1}"
        template_type = self._TEMPLATE_TYPES[index % 2]
        body_content = f"<p>{self.generate_random_text(10, 30)}</p>"

        template_data: dict[str, Any] = {
            "name": name,
            "templateType": template_type,
            "description": f"Auto-generated template #{index + 1}",
            "space": {"key": space_key},
            "body": {
                "storage": {
                    "value": body_content,
                    "representation": "storage",
                },
            },
        }

        if self.dry_run:
            self.logger.info(f"DRY RUN: Would create template '{name}' in space {space_key}")
            return {
                "templateId": f"dry-run-template-{space_key}-{index}",
                "name": name,
                "spaceKey": space_key,
            }

        base_url = f"{self.confluence_url}/rest/api"
        response = self._api_call("POST", "template", data=template_data, base_url=base_url)
        if response:
            result = response.json()
            template = {
                "templateId": result.get("templateId"),
                "name": result.get("name"),
                "spaceKey": space_key,
            }
            self.logger.info(f"Created template: {name}")
            return template

        self.logger.warning(f"Failed to create template '{name}'")
        return None

    def create_templates(
        self,
        spaces: list[dict[str, str]],
        count: int,
    ) -> list[dict[str, str]]:
        """Create multiple templates distributed across spaces.

        Args:
            spaces: List of space dicts with 'key' and 'id'
            count: Total number of templates to create

        Returns:
            List of template dicts with 'templateId', 'name', 'spaceKey'
        """
        if not spaces:
            return []

        self.logger.info(f"Creating {count} templates...")

        created_templates: list[dict[str, str]] = []

        for i in range(count):
            space = spaces[i % len(spaces)]
            space_key = space["key"]

            template = self.create_template(space_key, i)
            if template:
                created_templates.append(template)

            time.sleep(0.1)

        self.created_templates = created_templates
        return created_templates

    # ========== ASYNC METHODS ==========

    async def create_template_async(
        self,
        space_key: str,
        index: int,
    ) -> dict[str, str] | None:
        """Create a single content template asynchronously.

        Args:
            space_key: Space key to create the template in
            index: Template index (used for naming and type alternation)

        Returns:
            Dict with 'templateId', 'name', 'spaceKey' or None on failure
        """
        name = f"{self.prefix} Template {index + 1}"
        template_type = self._TEMPLATE_TYPES[index % 2]
        body_content = f"<p>{self.generate_random_text(10, 30)}</p>"

        template_data: dict[str, Any] = {
            "name": name,
            "templateType": template_type,
            "description": f"Auto-generated template #{index + 1}",
            "space": {"key": space_key},
            "body": {
                "storage": {
                    "value": body_content,
                    "representation": "storage",
                },
            },
        }

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would create template '{name}' in space {space_key}")
            return {
                "templateId": f"dry-run-template-{space_key}-{index}",
                "name": name,
                "spaceKey": space_key,
            }

        base_url = f"{self.confluence_url}/rest/api"
        success, result = await self._api_call_async("POST", "template", data=template_data, base_url=base_url)
        if success and result:
            template = {
                "templateId": result.get("templateId"),
                "name": result.get("name"),
                "spaceKey": space_key,
            }
            self.logger.info(f"Created template: {name}")
            return template

        self.logger.warning(f"Failed to create template '{name}'")
        return None

    async def create_templates_async(
        self,
        spaces: list[dict[str, str]],
        count: int,
    ) -> list[dict[str, str]]:
        """Create multiple templates asynchronously with batching.

        Templates have no hierarchy dependencies, so they can be created
        in parallel batches for better throughput.

        Args:
            spaces: List of space dicts with 'key' and 'id'
            count: Total number of templates to create

        Returns:
            List of template dicts
        """
        if not spaces:
            return []

        self.logger.info(f"Creating {count} templates (async, concurrency: {self.concurrency})...")

        created_templates: list[dict[str, str]] = []
        batch_size = self.concurrency * 2

        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)

            tasks = []
            for i in range(batch_start, batch_end):
                space = spaces[i % len(spaces)]
                space_key = space["key"]
                tasks.append(self.create_template_async(space_key, i))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, dict):
                    created_templates.append(result)
                elif isinstance(result, Exception):
                    self._record_error()
                    self.logger.error(f"Template creation failed with exception: {result}")

            self.logger.info(f"Created {len(created_templates)}/{count} templates")

        self.created_templates = created_templates
        return created_templates
