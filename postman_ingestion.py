#!/usr/bin/env python3
"""
Postman API Ingestion Script

Automates API discovery by ingesting OpenAPI specs into Postman Spec Hub,
generating collections with JWT auth, and syncing updates.

Usage:
    python postman_ingestion.py --spec resources/payment-refund-api-openapi.yaml
    python postman_ingestion.py --spec spec.yaml --export ./exports/ --sync
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import coloredlogs
import requests
import yaml
from dotenv import load_dotenv

# Set up colored logging
log = logging.getLogger(__name__)
coloredlogs.install(
    level="DEBUG",
    logger=log,
    fmt="%(levelname)s %(message)s",
    level_styles={
        "debug": {"color": "cyan"},
        "info": {"color": "green"},
        "warning": {"color": "yellow"},
        "error": {"color": "red", "bold": True},
    },
    field_styles={"levelname": {"color": "white", "bold": True}},
)

# Load environment variables from .env file in the script's directory
load_dotenv(Path(__file__).parent / ".env")

# Constants
POSTMAN_API_BASE = "https://api.getpostman.com"
DEFAULT_ENVIRONMENTS = {
    "Dev": "api-dev.payments.example.com",
    "QA": "api-qa.payments.example.com",
    "UAT": "api-uat.payments.example.com",
    "Prod": "api.payments.example.com",
}

# JWT Pre-request script for token caching
JWT_PREREQUEST_SCRIPT = """
// Token caching with automatic refresh
const tokenExpiry = pm.environment.get("token_expiry");
const cachedToken = pm.environment.get("jwt_token");

if (cachedToken && tokenExpiry && Date.now() < parseInt(tokenExpiry)) {
    pm.request.headers.add({
        key: "Authorization",
        value: "Bearer " + cachedToken
    });
    return;
}

const clientId = pm.environment.get("client_id");
const clientSecret = pm.environment.get("client_secret");
const tokenUrl = pm.environment.get("token_url");

if (!clientId || !clientSecret || !tokenUrl) {
    console.log("JWT auth variables not configured. Set client_id, client_secret, and token_url in environment.");
    return;
}

pm.sendRequest({
    url: tokenUrl,
    method: 'POST',
    header: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: {
        mode: 'urlencoded',
        urlencoded: [
            {key: 'grant_type', value: 'client_credentials'},
            {key: 'client_id', value: clientId},
            {key: 'client_secret', value: clientSecret}
        ]
    }
}, (err, response) => {
    if (!err && response.code === 200) {
        const data = response.json();
        pm.environment.set("jwt_token", data.access_token);
        // Cache token with 1 minute buffer before expiry
        pm.environment.set("token_expiry", Date.now() + (data.expires_in * 1000) - 60000);
        pm.request.headers.add({
            key: "Authorization",
            value: "Bearer " + data.access_token
        });
    } else {
        console.error("Failed to fetch JWT token:", err || response.status);
    }
});
""".strip()


class PostmanIngestion:
    """Handles Postman API operations for spec ingestion and collection management."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "X-Api-Key": api_key,
            "Content-Type": "application/json",
        })

    def _request(self, method: str, endpoint: str, suppress_errors: bool = False, **kwargs) -> dict:
        """Make an API request with error handling and rate limiting."""
        url = f"{POSTMAN_API_BASE}{endpoint}"
        max_retries = 3

        for attempt in range(max_retries):
            try:
                response = self.session.request(method, url, **kwargs)

                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    log.warning(f"Rate limited. Waiting {retry_after}s...")
                    time.sleep(retry_after)
                    continue

                response.raise_for_status()
                return response.json() if response.text else {}

            except requests.exceptions.HTTPError as e:
                if attempt == max_retries - 1:
                    if not suppress_errors:
                        log.error(f"{e}")
                        if response.text:
                            try:
                                error_detail = response.json()
                                log.error(f"Detail: {json.dumps(error_detail, indent=2)}")
                            except json.JSONDecodeError:
                                log.error(f"Response: {response.text[:500]}")
                    raise
                time.sleep(2 ** attempt)  # Exponential backoff

        return {}

    # =========================================================================
    # Workspace Management
    # =========================================================================

    def get_workspace(self, workspace_id: str) -> Optional[dict]:
        """Get workspace details by ID."""
        try:
            result = self._request("GET", f"/workspaces/{workspace_id}")
            return result.get("workspace")
        except requests.exceptions.HTTPError:
            return None

    def list_workspaces(self) -> list:
        """List all workspaces."""
        result = self._request("GET", "/workspaces")
        return result.get("workspaces", [])

    def create_workspace(self, name: str, description: str = "") -> str:
        """Create a new workspace."""
        payload = {
            "workspace": {
                "name": name,
                "type": "team",
                "description": description or f"Workspace for {name} APIs",
            }
        }
        result = self._request("POST", "/workspaces", json=payload)
        return result.get("workspace", {}).get("id")

    def get_or_create_workspace(
        self, workspace_id: Optional[str] = None, workspace_name: Optional[str] = None
    ) -> str:
        """Get existing workspace or create a new one."""
        if workspace_id:
            workspace = self.get_workspace(workspace_id)
            if workspace:
                return workspace_id
            log.warning(f"Workspace {workspace_id} not found, creating new...")

        # Create new workspace
        name = workspace_name or "API-Ingestion-Workspace"
        new_id = self.create_workspace(name)
        return new_id

    # =========================================================================
    # Spec Management (Spec Hub API)
    # =========================================================================

    def list_specs(self, workspace_id: str) -> list:
        """List all specs in a workspace using Spec Hub API."""
        result = self._request("GET", f"/specs?workspaceId={workspace_id}")
        return result.get("specs", [])

    def find_spec_by_name(self, workspace_id: str, spec_name: str) -> Optional[dict]:
        """Find a spec by name in the workspace. Returns the full spec dict or None."""
        specs = self.list_specs(workspace_id)
        for spec in specs:
            if spec.get("name") == spec_name:
                return spec
        return None

    def create_spec(self, workspace_id: str, spec_name: str, spec_content: str) -> str:
        """Create a new spec using Spec Hub API."""
        payload = {
            "name": spec_name,
            "type": "OPENAPI:3.0",
            "files": [{"path": "openapi.yaml", "content": spec_content}],
        }
        result = self._request("POST", f"/specs?workspaceId={workspace_id}", json=payload)
        return result.get("id")

    def upsert_spec(self, workspace_id: str, spec_path: str) -> tuple[str, bool]:
        """Create or find existing spec from file. Returns (spec_id, is_new)."""
        # Load and parse spec
        with open(spec_path, "r") as f:
            spec_content = f.read()

        spec_data = yaml.safe_load(spec_content)
        spec_name = spec_data.get("info", {}).get("title", Path(spec_path).stem)

        # Check if spec exists
        existing = self.find_spec_by_name(workspace_id, spec_name)

        if existing:
            log.info(f"   Found existing spec: {spec_name}")
            return existing.get("id"), False
        else:
            new_id = self.create_spec(workspace_id, spec_name, spec_content)
            return new_id, True

    # =========================================================================
    # Task Polling
    # =========================================================================

    def poll_task(self, task_url: str, max_attempts: int = 30) -> dict:
        """Poll async task until completed."""
        for i in range(max_attempts):
            result = self._request("GET", task_url)
            status = result.get("status")
            log.debug(f"Poll {i+1}: status={status}")

            if status == "completed":
                return result
            if status == "failed":
                log.error(f"Task failed: {result}")
                raise Exception(f"Task failed: {result}")

            time.sleep(2)

        raise Exception("Task polling timed out")

    # =========================================================================
    # Collection Generation & Management
    # =========================================================================

    def find_collection_by_name(self, workspace_id: str, name: str) -> Optional[dict]:
        """Find a collection by name in the workspace."""
        result = self._request("GET", f"/collections?workspaceId={workspace_id}")
        for col in result.get("collections", []):
            if col.get("name") == name:
                return col
        return None

    def generate_collection(self, spec_id: str, workspace_id: str, collection_name: str) -> Optional[str]:
        """Generate a collection from a spec using Spec Hub API with task polling."""
        # Check if collection already exists
        existing = self.find_collection_by_name(workspace_id, collection_name)
        if existing:
            log.info(f"   Found existing collection: {collection_name}")
            return existing.get("uid")

        payload = {
            "name": collection_name,
            "options": {
                "requestNameSource": "Fallback",
                "indentCharacter": "Tab",
                "folderStrategy": "Paths",
            },
        }

        result = self._request(
            "POST",
            f"/specs/{spec_id}/generations/collection",
            json=payload
        )

        # Handle async task
        if "taskId" in result:
            log.info("   Generating collection (async)...")
            task_result = self.poll_task(result["url"])
            resources = task_result.get("details", {}).get("resources", [])
            if not resources:
                log.error(f"No collection in task result: {task_result}")
                return None
            collection_id = resources[0]["id"]
            return collection_id

        # Synchronous response
        return result.get("collection", {}).get("id")

    def get_collection(self, collection_id: str) -> dict:
        """Get full collection details."""
        result = self._request("GET", f"/collections/{collection_id}")
        return result.get("collection", {})

    def update_collection(self, collection_id: str, collection_data: dict) -> None:
        """Update a collection."""
        self._request("PUT", f"/collections/{collection_id}", json={"collection": collection_data})

    # =========================================================================
    # JWT Pre-Request Script Injection
    # =========================================================================

    def add_jwt_prerequest_script(self, collection_id: str) -> None:
        """Add JWT pre-request script to collection."""
        collection = self.get_collection(collection_id)

        if not collection:
            log.warning(f"Could not fetch collection {collection_id}")
            return

        # Check if script already exists
        events = collection.get("event", [])
        has_prerequest = any(
            e.get("listen") == "prerequest" and
            "jwt_token" in str(e.get("script", {}).get("exec", []))
            for e in events
        )

        if has_prerequest:
            log.info("JWT script already present, skipping...")
            return

        # Add pre-request script
        prerequest_event = {
            "listen": "prerequest",
            "script": {
                "type": "text/javascript",
                "exec": JWT_PREREQUEST_SCRIPT.split("\n"),
            }
        }

        # Update events
        events = [e for e in events if e.get("listen") != "prerequest"]
        events.append(prerequest_event)
        collection["event"] = events

        self.update_collection(collection_id, collection)

    # =========================================================================
    # Environment Management
    # =========================================================================

    def list_environments(self, workspace_id: str) -> list:
        """List environments in a workspace."""
        result = self._request("GET", f"/environments?workspaceId={workspace_id}")
        return result.get("environments", [])

    def find_environment_by_name(self, workspace_id: str, name: str) -> Optional[str]:
        """Find an environment by name."""
        envs = self.list_environments(workspace_id)
        for env in envs:
            if env.get("name") == name:
                return env.get("id")
        return None

    def create_environment(
        self, workspace_id: str, name: str, base_url: str, api_version: str = "v2"
    ) -> str:
        """Create a new environment with standard variables."""
        full_base_url = f"https://{base_url}/{api_version}"
        payload = {
            "environment": {
                "name": name,
                "values": [
                    {"key": "base_url", "value": full_base_url, "enabled": True},
                    {"key": "client_id", "value": "", "enabled": True},
                    {"key": "client_secret", "value": "", "enabled": True, "type": "secret"},
                    {"key": "token_url", "value": "https://auth.example.com/oauth2/token", "enabled": True},
                    {"key": "jwt_token", "value": "", "enabled": True, "type": "secret"},
                    {"key": "token_expiry", "value": "", "enabled": True},
                ],
            }
        }
        result = self._request("POST", f"/environments?workspaceId={workspace_id}", json=payload)
        env_id = result.get("environment", {}).get("id")
        if env_id:
            log.info(f"   Created environment: {name}")
        else:
            log.warning(f"   Failed to create environment {name}: {result}")
        return env_id

    def update_environment(self, env_id: str, name: str, base_url: str, api_version: str = "v2") -> None:
        """Update an existing environment."""
        full_base_url = f"https://{base_url}/{api_version}"
        payload = {
            "environment": {
                "name": name,
                "values": [
                    {"key": "base_url", "value": full_base_url, "enabled": True},
                    {"key": "client_id", "value": "", "enabled": True},
                    {"key": "client_secret", "value": "", "enabled": True, "type": "secret"},
                    {"key": "token_url", "value": "https://auth.example.com/oauth2/token", "enabled": True},
                    {"key": "jwt_token", "value": "", "enabled": True, "type": "secret"},
                    {"key": "token_expiry", "value": "", "enabled": True},
                ],
            }
        }
        self._request("PUT", f"/environments/{env_id}", json=payload)

    def setup_all_environments(self, workspace_id: str, spec_data: dict) -> dict:
        """Create or update all environments from spec servers."""
        env_ids = {}

        # Parse servers from spec
        servers = spec_data.get("servers", [])
        env_mapping = {}

        for server in servers:
            url = server.get("url", "")
            desc = server.get("description", "").lower()

            # Extract host from URL
            host = url.replace("https://", "").replace("http://", "").split("/")[0]

            # Map to environment name
            if "prod" in desc:
                env_mapping["Prod"] = host
            elif "uat" in desc:
                env_mapping["UAT"] = host
            elif "qa" in desc:
                env_mapping["QA"] = host
            elif "dev" in desc:
                env_mapping["Dev"] = host

        # Fall back to defaults for missing environments
        for env_name, default_host in DEFAULT_ENVIRONMENTS.items():
            if env_name not in env_mapping:
                env_mapping[env_name] = default_host

        # Create or update environments
        for env_name, host in env_mapping.items():
            existing_id = self.find_environment_by_name(workspace_id, env_name)

            if existing_id:
                self.update_environment(existing_id, env_name, host)
                env_ids[env_name] = existing_id
                log.info(f"   Updated environment: {env_name}")
            else:
                env_id = self.create_environment(workspace_id, env_name, host)
                if env_id:
                    env_ids[env_name] = env_id

        return env_ids

    # =========================================================================
    # Export Functions
    # =========================================================================

    def export_collection(self, collection_id: str, output_path: str) -> str:
        """Export collection to JSON file."""
        collection = self.get_collection(collection_id)

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w") as f:
            json.dump({"collection": collection}, f, indent=2)

        return str(output_file)

    def get_environment(self, env_id: str) -> dict:
        """Get environment details."""
        result = self._request("GET", f"/environments/{env_id}")
        return result.get("environment", {})

    def export_environment(self, env_id: str, output_path: str) -> str:
        """Export environment to JSON file (with secrets redacted)."""
        env = self.get_environment(env_id)

        # Redact secrets
        values = env.get("values", [])
        for v in values:
            if v.get("type") == "secret":
                v["value"] = ""

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w") as f:
            json.dump({"environment": env}, f, indent=2)

        return str(output_file)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Ingest OpenAPI specs into Postman Spec Hub",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python postman_ingestion.py --spec resources/payment-refund-api.yaml
  python postman_ingestion.py --spec spec.yaml --export ./exports/
  WORKSPACE_ID=abc123 python postman_ingestion.py --spec spec.yaml --sync
        """,
    )
    parser.add_argument(
        "--spec",
        default=os.getenv("SPEC_PATH"),
        help="Path to OpenAPI spec file (YAML or JSON). Defaults to SPEC_PATH env var.",
    )
    parser.add_argument(
        "--export",
        metavar="DIR",
        nargs="?",
        const="./exports",
        default="./exports",
        help="Export collection and environments to directory (default: ./exports)",
    )
    parser.add_argument(
        "--no-export",
        action="store_true",
        help="Skip exporting collection and environments",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Force sync of linked collections",
    )
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()
    start_time = time.time()

    # Validate environment
    api_key = os.getenv("POSTMAN_API_KEY")
    if not api_key:
        log.error("POSTMAN_API_KEY environment variable is required")
        log.error("Set it in your .env file or export it in your shell")
        sys.exit(1)

    # Validate spec file
    if not args.spec:
        log.error("No spec file provided")
        log.error("Use --spec argument or set SPEC_PATH in your .env file")
        sys.exit(1)

    spec_path = Path(args.spec)
    if not spec_path.exists():
        log.error(f"Spec file not found: {spec_path}")
        sys.exit(1)

    # Load spec for metadata
    with open(spec_path, "r") as f:
        spec_content = f.read()
    spec_data = yaml.safe_load(spec_content)
    spec_name = spec_data.get("info", {}).get("title", spec_path.stem)
    spec_version = spec_data.get("info", {}).get("version", "1.0.0")

    log.info("Postman API Ingestion")
    log.info("=" * 50)

    # Initialize client
    client = PostmanIngestion(api_key)

    # 1. Workspace Management
    log.info("[1/6] Checking workspace...")
    workspace_id = os.getenv("WORKSPACE_ID")
    workspace_id = client.get_or_create_workspace(
        workspace_id=workspace_id,
        workspace_name=f"{spec_name} Workspace"
    )
    log.info(f"   Using workspace: {workspace_id}")

    # 2. Spec Management (Upsert)
    log.info(f"[2/6] Processing spec: {spec_name} v{spec_version}")
    spec_id, is_new = client.upsert_spec(workspace_id, str(spec_path))
    if is_new:
        log.info(f"   Created new spec: {spec_id}")
    else:
        log.info(f"   Using existing spec: {spec_id}")

    # 3. Collection Generation
    log.info("[3/6] Managing collections...")
    collection_id = client.generate_collection(spec_id, workspace_id, spec_name)
    if collection_id:
        log.info(f"   Collection ready: {collection_id}")
    else:
        log.warning("   Could not generate collection")

    # 4. Environment Setup
    log.info("[4/6] Setting up environments...")
    env_ids = client.setup_all_environments(workspace_id, spec_data)
    if not env_ids:
        log.warning("   No environments created")

    # 5. JWT Pre-Request Script Injection
    log.info("[5/6] Configuring JWT auth...")
    if collection_id:
        try:
            client.add_jwt_prerequest_script(collection_id)
            log.info("   JWT pre-request script added")
        except Exception as e:
            log.warning(f"Could not add JWT script ({e})")
    else:
        log.info("   Skipped (no collection)")

    # 6. Export (default enabled, use --no-export to skip)
    exported_files = []
    if not args.no_export and args.export:
        log.info(f"[6/6] Exporting to {args.export}...")
        export_dir = Path(args.export)

        if collection_id:
            # Generate safe filename from spec name
            safe_name = spec_name.lower().replace(" ", "-").replace(".", "-")
            safe_name = "".join(c for c in safe_name if c.isalnum() or c == "-")

            col_path = client.export_collection(
                collection_id,
                str(export_dir / f"{safe_name}-collection.json")
            )
            exported_files.append(col_path)
            log.info(f"   {col_path}")

        for env_name, env_id in env_ids.items():
            env_path = client.export_environment(
                env_id,
                str(export_dir / f"env-{env_name.lower()}.json")
            )
            exported_files.append(env_path)
            log.info(f"   {env_path}")
    else:
        log.info("[6/6] Export skipped (use --export DIR or remove --no-export)")

    # Summary
    elapsed = time.time() - start_time
    log.info("=" * 50)
    log.info("Complete!")
    log.info(f"   Workspace: https://www.postman.com/workspace/{workspace_id}")
    log.info(f"   Spec: https://www.postman.com/specs/{spec_id}")
    if collection_id:
        log.info(f"   Collection: https://www.postman.com/collection/{collection_id}")
    log.info(f"   Time: {elapsed:.1f} seconds")

    if not args.no_export and args.export and exported_files:
        log.info("# Run tests with Newman:")
        safe_name = spec_name.lower().replace(" ", "-").replace(".", "-")
        safe_name = "".join(c for c in safe_name if c.isalnum() or c == "-")
        log.info(f"newman run {args.export}/{safe_name}-collection.json \\")
        log.info(f"    -e {args.export}/env-dev.json \\")
        log.info(f"    --reporters cli,junit")


if __name__ == "__main__":
    main()
