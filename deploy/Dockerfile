# PythSol hosted playground image.
#
# Builds `pythsol serve --public --allow-compile`: visitors check, emit and
# compile typed Python to a Solana SBF `.so` from the browser. The container
# parses source with `ast` and never executes it; clang sees only
# compiler-generated C.
#
# The SBF toolchain is the official Anza platform-tools release, pinned by
# sha256, with the Rust toolchain stripped (PythSol compiles C only).
# Switch PYTHSOL_PLATFORM_TOOLS to move to a newer release and update the
# digest ARGs from the release page.
FROM python:3.12-slim

ARG PYTHSOL_PLATFORM_TOOLS=1.58
# platform-tools v1.58 digests (anza-xyz/platform-tools release assets).
ARG PT_SHA256_X86_64=7b82eb420b5aebd1e5590db0ae25c523eca06724d4238ae02139690535636c37
ARG PT_SHA256_AARCH64=9732174e2217ccfa489dfd644cf9bd86c46226be83354c03b832f1b421596870

ENV PYTHSOL_PLATFORM_TOOLS=${PYTHSOL_PLATFORM_TOOLS} \
    PYTHSOL_SBF_SDK=/opt/platform-tools \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHSOL_CACHE=/var/cache/pythsol

RUN apt-get update \
 && apt-get install -y --no-install-recommends bzip2 ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

# Fetch and unpack the toolchain for this machine's architecture.
RUN set -eux; \
    case "$(dpkg --print-architecture)" in \
      arm64) url=platform-tools-linux-aarch64.tar.bz2; digest=${PT_SHA256_AARCH64} ;; \
      *) url=platform-tools-linux-x86_64.tar.bz2; digest=${PT_SHA256_X86_64} ;; \
    esac; \
    curl -fsSLo /tmp/platform-tools.tar.bz2 \
      "https://github.com/anza-xyz/platform-tools/releases/download/v${PYTHSOL_PLATFORM_TOOLS}/${url}"; \
    echo "${digest}  /tmp/platform-tools.tar.bz2" | sha256sum -c -; \
    mkdir -p /opt/platform-tools; \
    tar -xjf /tmp/platform-tools.tar.bz2 -C /opt/platform-tools --strip-components=1; \
    rm /tmp/platform-tools.tar.bz2; \
    rm -rf /opt/platform-tools/rust \
           /opt/platform-tools/sdk/bpf/dependencies \
           /opt/platform-tools/sdk/aarch64-linux-musl; \
    /opt/platform-tools/llvm/bin/clang --version

# The package itself (src/ + pyproject.toml); click comes from dependencies.
COPY . /build
RUN pip install /build && rm -rf /build

# Cache dir must be writable by the runtime user.
RUN mkdir -p /var/cache/pythsol /tmp/pythsol-serve \
 && useradd -m -u 10001 pythsol \
 && chown -R pythsol:pythsol /var/cache/pythsol
USER pythsol

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4)"

EXPOSE 8080
CMD ["sh", "-c", "exec pythsol serve --public --host 0.0.0.0 --port ${PORT:-8080} --allow-compile"]
