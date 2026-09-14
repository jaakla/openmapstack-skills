# Build a clean runtime; do not COPY the repository or host agent state.
# Supply a pinned Node base image and exact CLI versions at build time.
# Run the resulting local sha256 image ID, never a mutable tag.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG CLAUDE_CODE_VERSION
ARG CODEX_VERSION
RUN test -n "$CLAUDE_CODE_VERSION" && test -n "$CODEX_VERSION" \
    && apt-get update && apt-get install -y --no-install-recommends python3 \
    && npm install --global "@anthropic-ai/claude-code@$CLAUDE_CODE_VERSION" "@openai/codex@$CODEX_VERSION" \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
