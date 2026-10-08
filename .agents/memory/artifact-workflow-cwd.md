---
name: Artifact workflow working directory
description: How relative paths resolve in managed artifact service commands.
---

Managed artifact service commands run with the artifact directory as their working directory. Artifact-local files can be referenced directly; workspace-root files and package projects are reached with `../..`.

**Why:** A command that assumes the workspace root can start successfully but fail to find the app entry file or package project.

**How to apply:** When setting a service command in `artifact.toml`, write paths relative to the artifact directory and point `uv` or other root-level package tools to `../..`.
