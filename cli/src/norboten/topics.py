"""The topic taxonomy — the axes everything is measured in.

A learner has one rating per topic, the profile radar has one spoke per topic, every lab declares
the topics it exercises and every question inherits them from its bank. The list is derived from
the RHCSA (EX200) objectives and the Red Hat troubleshooting exam (EX342), plus the automation
subjects this project teaches on top of them. It is deliberately short: nineteen axes still read
on a radar chart, and a rating needs enough attempts per axis to mean anything.

Slugs are permanent. They appear in stored ratings, in lab manifests and in URLs, so renaming one
is a migration, not an edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TopicGroup(StrEnum):
    """How the topics cluster on the profile page and in the docs."""

    SYSTEM = "system"
    NETWORK = "network"
    DIAGNOSTICS = "diagnostics"
    SCRIPTING = "scripting"
    AUTOMATION = "automation"
    AI = "ai"


@dataclass(frozen=True, slots=True)
class Topic:
    slug: str
    title: str
    group: TopicGroup
    blurb: str


TOPICS: tuple[Topic, ...] = (
    Topic(
        "linux-basics",
        "Linux basics",
        TopicGroup.SYSTEM,
        "Files, processes, packages and the shell you meet them through.",
    ),
    Topic(
        "users-permissions",
        "Users and permissions",
        TopicGroup.SYSTEM,
        "Accounts, groups, modes, setgid directories, umask and sudo rules.",
    ),
    Topic(
        "storage-lvm",
        "Storage and LVM",
        TopicGroup.SYSTEM,
        "Partitions, filesystems, fstab, logical volumes, swap and what fills a disk.",
    ),
    Topic(
        "boot-systemd",
        "Boot and systemd",
        TopicGroup.SYSTEM,
        "Units, targets, drop-ins, timers, the bootloader and the emergency shell.",
    ),
    Topic(
        "networking",
        "Networking",
        TopicGroup.NETWORK,
        "Addresses, routes, name resolution, ports and persistent connection config.",
    ),
    Topic(
        "firewall-selinux",
        "Firewall and SELinux",
        TopicGroup.NETWORK,
        "firewalld zones and services, file contexts, port labels and booleans.",
    ),
    Topic(
        "kernel-performance",
        "Kernel and performance",
        TopicGroup.DIAGNOSTICS,
        "Limits, sysctl, memory pressure, and finding what actually costs the time.",
    ),
    Topic(
        "logging-journald",
        "Logging and journald",
        TopicGroup.DIAGNOSTICS,
        "Reading the journal, persistence, rotation and log hygiene.",
    ),
    Topic(
        "monitoring",
        "Monitoring",
        TopicGroup.DIAGNOSTICS,
        "Health checks, metrics, alerts and knowing a service is down before a user says so.",
    ),
    Topic(
        "bash",
        "Bash",
        TopicGroup.SCRIPTING,
        "Quoting, exit status, strict mode, pipelines and scripts that fail honestly.",
    ),
    Topic(
        "python",
        "Python",
        TopicGroup.SCRIPTING,
        "Virtual environments, packaging, service accounts and small automation programs.",
    ),
    Topic(
        "ansible",
        "Ansible",
        TopicGroup.AUTOMATION,
        "Inventories, playbooks, roles, idempotence and templated configuration.",
    ),
    Topic(
        "terraform",
        "Terraform",
        TopicGroup.AUTOMATION,
        "Providers, state, modules, plan discipline and what a destroy really touches.",
    ),
    Topic(
        "containers",
        "Containers",
        TopicGroup.AUTOMATION,
        "Images, registries, rootless runtimes, volumes and container-managed services.",
    ),
    Topic(
        "ai-services",
        "AI Services",
        TopicGroup.AI,
        "Model servers and APIs behind a proxy: reachability, credentials, rate limits, embeddings "
        "and retrieval.",
    ),
    Topic(
        "ai-agents",
        "AI Agents",
        TopicGroup.AI,
        "Agent jobs that act through tools: permissions, turn caps, budgets and prompt injection.",
    ),
    Topic(
        "claude-code",
        "Claude Code",
        TopicGroup.AI,
        "Headless runs, permission rules, hooks, subagents, MCP servers and CI jobs on a budget.",
    ),
    Topic(
        "ollama",
        "Ollama",
        TopicGroup.AI,
        "Local models: pulling, memory, context length, the API and keeping it off the network.",
    ),
    Topic(
        "mcp",
        "Model Context Protocol",
        TopicGroup.AI,
        "MCP servers and clients: transports, what a server exposes, tool results as untrusted "
        "input, tokens and their audience, proxies in between.",
    ),
)

BY_SLUG: dict[str, Topic] = {t.slug: t for t in TOPICS}
SLUGS: tuple[str, ...] = tuple(t.slug for t in TOPICS)


def get(slug: str) -> Topic:
    try:
        return BY_SLUG[slug]
    except KeyError:
        raise KeyError(f"unknown topic {slug!r}; known topics: {', '.join(SLUGS)}") from None


def grouped() -> list[tuple[TopicGroup, list[Topic]]]:
    """The taxonomy in display order, clustered by group."""
    out: list[tuple[TopicGroup, list[Topic]]] = []
    for group in TopicGroup:
        members = [t for t in TOPICS if t.group is group]
        if members:
            out.append((group, members))
    return out
