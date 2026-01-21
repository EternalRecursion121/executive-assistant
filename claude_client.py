"""Claude Code CLI integration client."""

import asyncio
import json
from pathlib import Path
from typing import Optional


class ClaudeClient:
    """Wrapper for Claude Code CLI with session persistence."""

    def __init__(
        self,
        workspace: Path,
        timeout: int = 300,
        claude_path: str = "claude",
    ):
        self.workspace = Path(workspace)
        self.timeout = timeout
        self.claude_path = claude_path
        self.session_file = self.workspace / ".claude_session_id"
        self.lock = asyncio.Lock()

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
        async with self.lock:
            session_id = self._get_session_id()

            # Build command
            cmd = [
                self.claude_path,
                "--print",
                "--output-format", "stream-json",
            ]

            if system_prompt:
                cmd.extend(["--system-prompt", system_prompt])

            if session_id:
                cmd.extend(["--resume", session_id])

            cmd.append(message)

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
                # Parse streaming JSON output
                while True:
                    try:
                        line = await asyncio.wait_for(
                            process.stdout.readline(),
                            timeout=self.timeout,
                        )
                    except asyncio.TimeoutError:
                        process.kill()
                        return "Request timed out. Please try again."

                    if not line:
                        break

                    try:
                        data = json.loads(line.decode())

                        # Extract session ID from init message
                        if data.get("type") == "system" and data.get("subtype") == "init":
                            new_session_id = data.get("session_id")

                        # Collect response text from assistant messages
                        if data.get("type") == "assistant" and "message" in data:
                            for block in data["message"].get("content", []):
                                if block.get("type") == "text":
                                    full_response += block.get("text", "")

                    except json.JSONDecodeError:
                        continue

                await process.wait()

            except Exception as e:
                process.kill()
                return f"Error communicating with Claude: {e}"

            # Save session for conversation continuity
            if new_session_id:
                self._save_session_id(new_session_id)

            return full_response.strip() if full_response else "No response received."

    async def reset_session(self) -> None:
        """Clear the current session to start fresh."""
        async with self.lock:
            if self.session_file.exists():
                self.session_file.unlink()
