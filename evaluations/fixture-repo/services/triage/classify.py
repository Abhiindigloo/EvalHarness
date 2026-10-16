import os
import anthropic

client = anthropic.Anthropic()
MODEL = os.getenv("TRIAGE_MODEL", "claude-haiku-4-5")
ESCALATION_MODEL = "claude-sonnet-4-5"
