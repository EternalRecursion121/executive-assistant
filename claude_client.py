"""Claude Code CLI integration client."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ClaudeClient:
    """Wrapper for Claude Code CLI with session persistence."""

    def __init__(
        self,
        workspace: Path,
        timeout: int = 600,
        claude_path: str = "claude",
    ):
        self.workspace = Path(workspace)
        self.timeout = timeout
        self.claude_path = claude_path
        self.session_file = self.workspace / ".claude_session_id"

        # Ensure workspace exists
        self.workspace.mkdir(parents=True, exist_ok=True)

    def _get_session_id(self) -> Optional[str]:
        """Load existing session ID if available."""
        if self.session_file.exists():
            session_id = self.session_file.read_text().strip()
            if session_id:
                return session_id
        return None

    def _save_session_id(self, session_id: str) -> None:
        """Persist session ID for future messages."""
        self.session_file.write_text(session_id)

    async def send(
        self,
        message: str,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Send a message to Claude and get the response.

        Args:
            message: The user message to send
            system_prompt: Optional system prompt to set context

        Returns:
            Claude's text response
        """
        # Build command (no session resume - keeps responses fast)
        cmd = [
            self.claude_path,
            "--print",
            "--verbose",
            "--output-format", "stream-json",
            "--dangerously-skip-permissions",
        ]

        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])

        cmd.append(message)

        logger.info(f"Running claude command: {' '.join(cmd[:6])}...")

        # Execute Claude CLI
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.workspace),
        )

        full_response = ""
        new_session_id = None

        try:
            # Read all stdout at once to avoid readline buffer limits on large JSON
            try:
                stdout_data, stderr_data = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                return "Request timed out. Please try again."

            # Parse streaming JSON output line by line
            for line in stdout_data.decode().splitlines():
                if not line.strip():
                    continue

                try:
                    data = json.loads(line)
                    logger.debug(f"Claude JSON type: {data.get('type')}")

                    # Extract session ID from init message
                    if data.get("type") == "system" and data.get("subtype") == "init":
                        new_session_id = data.get("session_id")

                    # Get final response from result message
                    if data.get("type") == "result":
                        logger.info(f"Result message: {json.dumps(data)[:500]}")
                        full_response = data.get("result", "")
                        if data.get("session_id"):
                            new_session_id = data.get("session_id")

                except json.JSONDecodeError as e:
                    logger.warning(f"JSON decode error: {e}, line: {line[:100]}")
                    continue

            # Check stderr for errors
            if stderr_data:
                logger.error(f"Claude stderr: {stderr_data.decode()}")

        except Exception as e:
            process.kill()
            logger.error(f"Exception in Claude call: {e}")
            return f"Error communicating with Claude: {e}"

        logger.info(f"Claude response length: {len(full_response)}")

        # Save session for conversation continuity
        if new_session_id:
            self._save_session_id(new_session_id)

        return full_response.strip() if full_response else "No response received."

    async def reset_session(self) -> None:
        """Clear the current session to start fresh."""
        if self.session_file.exists():
            self.session_file.unlink()

    async def should_respond(
        self,
        context: str,
        system_prompt: Optional[str] = None,
    ) -> bool:
        """Decide whether to respond to a message that wasn't directly addressed to us.

        Uses a quick Claude call to decide if the message warrants a response.
        """
        decision_prompt = f"""You are observing a Discord channel. A message was sent that wasn't directly addressed to you.

Context (recent messages):
{context}

Should you respond to this? Consider:
- Is the message asking a question you can help with?
- Is someone talking about something you have relevant insight on?
- Would your input add value, or would it be intrusive?
- Is this just casual chat that doesn't need your input?

Reply with ONLY "yes" or "no" - nothing else."""

        # Use a simpler, faster call without session persistence
        cmd = [
            self.claude_path,
            "--print",
            "--output-format", "text",
            "--dangerously-skip-permissions",
            "--model", "haiku",  # Use haiku for fast decisions
            "-p", decision_prompt,
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace),
            )

            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=30,  # Quick timeout for decision
            )

            response = stdout.decode().strip().lower()
            logger.info(f"Should respond decision: {response}")
            return response == "yes"

        except Exception as e:
            logger.error(f"Error in should_respond: {e}")
            return False  # Default to not responding on error
