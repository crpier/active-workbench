# Active Workbench - Implementation Plan

**Updated:** 2026-02-08

## Goal

Build a personal assistant platform that manages notes, journals, recipes, and digital context through agent interaction only.

## Scope

In scope:
- Agent-first interaction (chat first, voice-enabled)
- Markdown knowledge management for durable content
- External read-only integrations by default
- Automatic memory capture with user-visible undo controls

Out of scope:
- CLI-based user workflows
- Manual-first curation systems
- Custom in-house LLM runtime

## Architecture

1. Agent runtime
- OpenCode in server mode
- Skills/plugins for behavior adaptation
- Access only through approved tools

2. Backend control plane
- FastAPI tool endpoints for vault, memory, and integrations
- Action audit records for sensitive operations

3. Storage model
- Markdown is canonical for notes/journals/recipes
- SQLite holds index, metadata, and memory records

4. Client channels
- Chat UI as primary interface
- Android and smartwatch voice as input channels

5. Deployment
- VPS provisioned and managed with Nix/NixOS
- Least-privilege service boundaries and managed secrets

## Security and Memory

Security defaults:
- Tool allowlist only
- Connector isolation and narrow OAuth scopes
- Read-only integrations unless explicitly expanded

Memory policy (opt-out):
1. Agent saves reusable facts by default
2. User receives notification with source context
3. User can undo or delete memory entries
4. Sensitive categories can require explicit confirmation

## Phases

1. Foundation realignment
- Align product/docs to agent-only direction
- Define tool contracts between agent and backend

2. Secure VPS baseline
- Provision Nix/NixOS host
- Deploy backend and agent runtime

3. Core tooling and memory
- Implement vault and memory APIs
- Add audit and undo flows

4. First integrations
- YouTube read-only connector
- Email read-only connector

5. Voice and device stabilization
- Android and smartwatch flow integration
- Reliable speech-to-text and notifications

## Success Criteria

- Daily use happens through the agent, not CLI
- Vault actions are reliable and auditable
- Memory improves continuity and stays user-controllable
- First integration workflow works end-to-end safely
