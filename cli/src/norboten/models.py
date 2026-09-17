"""Pydantic models shared by the CLI and the API.

This module is the machine-readable form of docs/lab-spec.md. Keep the two in step.
"""

from __future__ import annotations

import random
import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from norboten import topics

SCHEMA_VERSION = 1

_SIZE_RE = re.compile(r"^(\d+(?:\.\d+)?)(MiB|GiB)$")
_UNITS = {"MiB": 1024**2, "GiB": 1024**3}


def parse_size(value: str) -> int:
    """'512MiB' -> bytes. Binary units only, so there is exactly one way to write a size."""
    m = _SIZE_RE.match(value.strip())
    if not m:
        raise ValueError(f"size {value!r} must look like '512MiB' or '2GiB'")
    return int(float(m.group(1)) * _UNITS[m.group(2)])


def format_size(n: int) -> str:
    if n >= 1024**3:
        return f"{n / 1024**3:.1f} GiB"
    return f"{n / 1024**2:.0f} MiB"


def _valid_size(value: str) -> str:
    parse_size(value)
    return value


def _known_topic(value: str) -> str:
    if value not in topics.BY_SLUG:
        raise ValueError(f"unknown topic {value!r}; known topics: {', '.join(topics.SLUGS)}")
    return value


Size = Annotated[str, AfterValidator(_valid_size)]
Slug = Annotated[str, Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=63)]
#: A base image id may carry a version with a dot in it: `ubuntu-26.04`.
ImageId = Annotated[str, Field(pattern=r"^[a-z0-9]+([.-][a-z0-9]+)*$", max_length=63)]
CheckId = Annotated[str, Field(pattern=r"^\d{2}_[a-z0-9_]+$")]
TopicSlug = Annotated[str, AfterValidator(_known_topic)]

# Rated attempts are timed. A practical lab gets the minutes its difficulty buys, unless the lab
# sets its own limit (the exam simulation does). A question gets seconds by difficulty, with a
# grace allowance when it makes you read a snippet.
LAB_MINUTES_BY_DIFFICULTY = {1: 5, 2: 10, 3: 15, 4: 20, 5: 30}
QUESTION_SECONDS_BY_DIFFICULTY = {1: 15, 2: 15, 3: 20, 4: 25, 5: 30}
QUESTION_CODE_GRACE_SECONDS = 10


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------------------
# Base image registry — images/registry.yaml
# ---------------------------------------------------------------------------


class Track(StrEnum):
    RHCSA = "rhcsa"
    LINUX = "linux"
    AUTOMATION = "automation"
    PYTHON = "python"
    ANSIBLE = "ansible"
    BASH = "bash"
    DOCKER = "docker"
    TERRAFORM = "terraform"
    CLAUDE = "claude"
    MCP = "mcp"
    INTRO = "intro"


class Arch(StrEnum):
    X86_64 = "x86_64"
    AARCH64 = "aarch64"


class UpstreamImage(_Strict):
    url: str
    digest: Annotated[str, Field(pattern=r"^sha(256|512):[0-9a-f]+$")]


class GoldenArtifact(_Strict):
    digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    size_bytes: Annotated[int, Field(gt=0)]


class GoldenImage(_Strict):
    ref: str = Field(description="OCI repository, e.g. ghcr.io/owner/norboten-base/rocky-10")
    tag: str | None = Field(default=None, description="null until the first publish")
    arch: dict[Arch, GoldenArtifact] = Field(default_factory=dict)


class ContainerBuild(_Strict):
    """A container base image: built on the learner's machine from a Dockerfile in the content."""

    dockerfile: str = Field(
        description="path under images/, e.g. base/ubuntu-26.04-container/Dockerfile"
    )
    tag: str = Field(
        description="the local image name, e.g. norboten-base/ubuntu-26.04-container:1"
    )


class BaseImage(_Strict):
    distro: str
    tracks: list[Track] = Field(min_length=1)
    kind: Literal["vm", "container"] = "vm"
    init: Literal["systemd", "openrc", "none"]
    pkg: Literal["dnf", "apt", "apk"]
    mac: Literal["selinux", "apparmor", "none"]
    min_memory: Size
    upstream: dict[Arch, UpstreamImage] = Field(default_factory=dict)
    golden: GoldenImage | None = None
    container: ContainerBuild | None = None

    @property
    def min_memory_bytes(self) -> int:
        return parse_size(self.min_memory)

    @model_validator(mode="after")
    def _kind(self) -> BaseImage:
        if self.kind == "vm":
            if not self.upstream or self.golden is None or self.container is not None:
                raise ValueError("a vm image needs upstream and golden, and no container block")
            if self.init == "none":
                raise ValueError("a vm image boots an init system")
        else:
            if self.container is None or self.upstream or self.golden is not None:
                raise ValueError("a container image needs a container block and no upstream/golden")
            if self.init != "none":
                raise ValueError("a container image runs no init system: init must be none")
        return self


class Registry(_Strict):
    schema_version: Literal[1]
    images: dict[ImageId, BaseImage] = Field(min_length=1)

    def get(self, image_id: str) -> BaseImage:
        try:
            return self.images[image_id]
        except KeyError:
            known = ", ".join(self.images)
            raise KeyError(f"unknown base image {image_id!r} (known: {known})") from None

    def serving(self, track: Track) -> list[str]:
        return [i for i, img in self.images.items() if track in img.tracks]


# ---------------------------------------------------------------------------
# Lab manifest — lab.yaml
# ---------------------------------------------------------------------------


class Disk(_Strict):
    size: Size

    @field_validator("size")
    @classmethod
    def _bounds(cls, v: str) -> str:
        if not 1024**3 <= parse_size(v) <= 32 * 1024**3:
            raise ValueError("extra disks must be between 1GiB and 32GiB")
        return v


class Resources(_Strict):
    cpus: Annotated[int, Field(ge=1, le=4)] = 1
    memory: Size | None = None
    disks: Annotated[list[Disk], Field(max_length=4)] = Field(default_factory=list)


class CheckRef(_Strict):
    id: CheckId
    objective: Annotated[int, Field(ge=1)]
    weight: Annotated[int, Field(ge=1, le=10)] = 1
    baseline_pass: bool = False
    # passes while a boot_after_break machine sits at a maintenance prompt, because what it
    # observes (a running service, a mounted volume) cannot exist there — docs/lab-spec.md §9
    maintenance_pass: bool = False


class LabManifest(_Strict):
    schema_version: Literal[1]
    id: Slug
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    title: Annotated[str, Field(min_length=3, max_length=60)]
    track: Track
    topics: Annotated[list[TopicSlug], Field(min_length=1, max_length=5)]
    difficulty: Annotated[int, Field(ge=1, le=5)]
    estimated_minutes: Annotated[int, Field(ge=5, le=240)]
    base_images: list[ImageId] = Field(min_length=1)
    runtime: Literal["vm", "container"] = "vm"
    resources: Resources = Field(default_factory=Resources)
    objectives: list[Annotated[str, Field(min_length=3)]] = Field(min_length=1)
    checks: list[CheckRef] = Field(min_length=1)
    reboot_required: bool
    boot_after_break: bool = False
    time_limit_minutes: Annotated[int, Field(ge=5)] | None = None
    pass_percent: Annotated[int, Field(ge=1, le=100)] = 100
    #: a rated lab (docs/lab-spec.md §13): graded on the server, from the private repository
    rated: bool = False

    @property
    def rated_minutes(self) -> int:
        """The clock a rated attempt runs against (docs/lab-spec.md §9)."""
        return self.time_limit_minutes or LAB_MINUTES_BY_DIFFICULTY[self.difficulty]

    @model_validator(mode="after")
    def _consistency(self, info: ValidationInfo) -> LabManifest:
        if len(set(self.base_images)) != len(self.base_images):
            raise ValueError("base_images must be unique")
        if len(set(self.topics)) != len(self.topics):
            raise ValueError("topics must be unique")
        ids = [c.id for c in self.checks]
        if len(set(ids)) != len(ids):
            raise ValueError("check ids must be unique")
        if ids != sorted(ids):
            raise ValueError("checks must be listed in file order (sorted by id)")
        n = len(self.objectives)
        for c in self.checks:
            if c.objective > n:
                raise ValueError(f"check {c.id} refers to objective {c.objective}; only {n} exist")
        uncovered = set(range(1, n + 1)) - {c.objective for c in self.checks}
        if uncovered:
            raise ValueError(f"objectives without a check: {sorted(uncovered)}")
        flagged = [c.id for c in self.checks if c.maintenance_pass]
        if flagged and not self.boot_after_break:
            raise ValueError(f"maintenance_pass needs boot_after_break: {', '.join(flagged)}")
        if self.runtime == "container" and (self.reboot_required or self.boot_after_break):
            raise ValueError("container labs cannot reboot")
        if self.runtime == "vm" and self.track != Track.INTRO and not self.reboot_required:
            raise ValueError("every vm lab outside the intro track must be reboot_required")

        registry: Registry | None = (info.context or {}).get("registry")
        if registry is not None:
            self.check_against(registry)
        return self

    def check_against(self, registry: Registry) -> None:
        """Rules that need the base image registry: track binding and memory floor."""
        for image_id in self.base_images:
            try:
                image = registry.get(image_id)
            except KeyError as e:
                raise ValueError(e.args[0]) from None
            if self.track not in image.tracks:
                raise ValueError(
                    f"{self.track.value!r} labs cannot run on {image_id!r}; "
                    f"allowed base images: {registry.serving(self.track)}"
                )
            if (image.kind == "container") != (self.runtime == "container"):
                raise ValueError(
                    f"a {self.runtime} lab cannot run on {image_id!r}, a {image.kind} image"
                )
            if self.runtime == "container" and self.resources.disks:
                raise ValueError("container labs cannot have extra disks")
            if self.resources.memory and parse_size(self.resources.memory) < image.min_memory_bytes:
                raise ValueError(
                    f"resources.memory {self.resources.memory} is below {image_id}'s "
                    f"min_memory {image.min_memory}"
                )

    @property
    def total_weight(self) -> int:
        return sum(c.weight for c in self.checks)

    @property
    def short_id(self) -> str:
        """'rhcsa-03-storage-and-lvm' -> 'rhcsa-03'. Ids without a number stay as they are."""
        m = re.match(r"^([a-z][a-z0-9]*-\d{2})(-|$)", self.id)
        return m.group(1) if m else self.id

    def memory_for(self, registry: Registry, image_id: str) -> int:
        floor = registry.get(image_id).min_memory_bytes
        return max(floor, parse_size(self.resources.memory)) if self.resources.memory else floor


#: Where a hint points for reading: a journal section, a manual page, or official documentation.
#:   journal:<topic slug or lab id>#<heading anchor>    man <section> <page>    https://…
HintRef = Annotated[
    str,
    Field(
        pattern=r"^(journal:[a-z0-9-]+#[a-z0-9_-]+|man [1-9][a-z]* [A-Za-z0-9_.:+@-]+|https://\S+)$"
    ),
]


class HintLadder(_Strict):
    level_1: Annotated[str, Field(min_length=10)]
    level_2: Annotated[str, Field(min_length=10)]
    level_3: Annotated[str, Field(min_length=10)]
    level_4: Annotated[str, Field(min_length=10)]
    #: Reading for a level, shown with it and with every level after it (docs/lab-spec.md §7).
    refs: dict[Annotated[int, Field(ge=1, le=4)], list[HintRef]] = Field(default_factory=dict)

    def level(self, n: int) -> str:
        if n not in (1, 2, 3, 4):
            raise ValueError("hint level must be 1-4")
        return getattr(self, f"level_{n}")

    def refs_upto(self, n: int) -> list[str]:
        """The reading a learner at hint level `n` may see: levels 1 to n, each once, in order."""
        out: list[str] = []
        for level in range(1, n + 1):
            out += [r for r in self.refs.get(level, []) if r not in out]
        return out


class Hints(_Strict):
    checks: dict[CheckId, HintLadder]


# ---------------------------------------------------------------------------
# Results — runner -> CLI -> API
# ---------------------------------------------------------------------------


class Phase(StrEnum):
    LIVE = "live"
    PRE_REBOOT = "pre_reboot"
    POST_REBOOT = "post_reboot"


class CheckResult(BaseModel):
    id: str
    passed: bool
    message: str
    evidence: str = ""


class PassResult(BaseModel):
    phase: Phase
    results: list[CheckResult]


class ObjectiveScore(BaseModel):
    objective: str
    passed_weight: int
    total_weight: int


class GradeReport(BaseModel):
    lab_id: str
    lab_version: str
    base_image: str
    passes: list[PassResult]
    score_percent: int
    passed: bool
    graded: bool = Field(
        default=True, description="False for a quick check that skipped a required reboot"
    )
    over_time: bool = False
    objectives: list[ObjectiveScore] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Theory questions — docs/quiz-spec.md
# ---------------------------------------------------------------------------

QuestionId = Annotated[str, Field(pattern=r"^[a-z0-9]+-\d{3}$")]
_BANNED_CHOICES = re.compile(r"\b(all|none|both) of the above\b|\bboth [a-f] and [a-f]\b", re.I)


class Choice(_Strict):
    id: Literal["a", "b", "c", "d", "e", "f"]
    text: Annotated[str, Field(min_length=1, max_length=300)]


class Verify(_Strict):
    runtime: Literal["bash", "python"]
    code: Annotated[str, Field(min_length=1, max_length=4000)]
    expect: Literal["output_is_answer"] = "output_is_answer"


class Question(_Strict):
    id: QuestionId
    type: Literal["single", "multiple"]
    difficulty: Annotated[int, Field(ge=1, le=5)]
    prompt: Annotated[str, Field(min_length=10, max_length=600)]
    code: str | None = None
    code_lang: Literal["bash", "python", "hcl", "yaml", "json", "text"] = "text"
    choices: Annotated[list[Choice], Field(min_length=3, max_length=6)]
    answer: Annotated[list[Literal["a", "b", "c", "d", "e", "f"]], Field(min_length=1)]
    explanation: Annotated[str, Field(min_length=30)]
    references: Annotated[list[str], Field(min_length=1)]
    tags: list[str] = Field(default_factory=list)
    topics: list[TopicSlug] = Field(default_factory=list)
    verify: Verify | None = None

    @property
    def time_limit_seconds(self) -> int:
        """A rated question is timed; reading a snippet buys a grace allowance."""
        base = QUESTION_SECONDS_BY_DIFFICULTY[self.difficulty]
        return base + (QUESTION_CODE_GRACE_SECONDS if self.code else 0)

    def topics_in(self, bank: QuestionBank) -> list[str]:
        """The question's own topics, or the bank's if it does not narrow them."""
        return self.topics or list(bank.topics)

    @model_validator(mode="after")
    def _consistent(self) -> Question:
        ids = [c.id for c in self.choices]
        if ids != ["a", "b", "c", "d", "e", "f"][: len(ids)]:
            raise ValueError("choice ids must be a, b, c… in order")
        texts = [c.text.strip() for c in self.choices]
        if len(set(texts)) != len(texts):
            raise ValueError("choice texts must be unique")
        if any(_BANNED_CHOICES.search(c.text) for c in self.choices):
            raise ValueError("'all/none/both of the above' choices are not allowed")
        if len(set(self.answer)) != len(self.answer) or not set(self.answer) <= set(ids):
            raise ValueError("answer must list existing choice ids, once each")
        if self.type == "single" and len(self.answer) != 1:
            raise ValueError("a single-choice question has exactly one answer")
        if self.verify is not None and self.type != "single":
            raise ValueError("executable verification applies to single-choice questions")
        return self

    def is_correct(self, selected: set[str]) -> bool:
        return selected == set(self.answer)

    def shuffled(self, rng: random.Random) -> Question:
        """The same question with its choices in another order, relabelled a, b, c… and the answer
        following them — so the right answer is never always in one place. An explanation must
        therefore never name a choice by its letter."""
        order = list(range(len(self.choices)))
        rng.shuffle(order)
        letters = "abcdef"
        new_id = {self.choices[old].id: letters[pos] for pos, old in enumerate(order)}
        choices = [
            self.choices[old].model_copy(update={"id": letters[pos]})
            for pos, old in enumerate(order)
        ]
        return self.model_copy(
            update={"choices": choices, "answer": sorted(new_id[a] for a in self.answer)}
        )

    def choice_text(self, choice_id: str) -> str:
        return next(c.text for c in self.choices if c.id == choice_id)


class QuestionBank(_Strict):
    schema_version: Literal[1]
    topic: Slug
    topics: Annotated[list[TopicSlug], Field(min_length=1, max_length=5)]
    title: Annotated[str, Field(min_length=2, max_length=60)]
    description: Annotated[str, Field(min_length=10, max_length=300)]
    questions: Annotated[list[Question], Field(min_length=1)]

    @model_validator(mode="after")
    def _unique_ids(self) -> QuestionBank:
        ids = [q.id for q in self.questions]
        if len(set(ids)) != len(ids):
            raise ValueError("question ids must be unique within a bank")
        return self
