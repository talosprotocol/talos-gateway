# Agent workspace: services/gateway
> **Project**: services/gateway

This folder contains agent-facing context, tasks, workflows, and planning artifacts for this submodule.

## Current State
Edge entry point. Multi-region read and write split is active or in progress, with rate limiting and request validation expected. A2A and capability enforcement paths are implemented in the gateway layer.

## Expected State
High availability with minimal overhead and strict fail-closed security. All inputs validated against contracts before dispatch.

## Behavior
Routes and mediates requests to internal services and tool servers. Enforces authN, authZ, auditing hooks, and safety limits.

## How to work here
- Run/tests:
- Local dev:
- CI notes:

## Interfaces and dependencies
- Owned APIs/contracts:
- Depends on:
- Data stores/events (if any):

## Global context
See `.agent/context.md` for monorepo-wide invariants and architecture.
